# Copyright (c) 2005-2009, Alexander Belchenko
# All rights reserved.
#
# Redistribution and use in source and binary forms,
# with or without modification, are permitted provided
# that the following conditions are met:
#
# * Redistributions of source code must retain
#   the above copyright notice, this list of conditions
#   and the following disclaimer.
# * Redistributions in binary form must reproduce
#   the above copyright notice, this list of conditions
#   and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# * Neither the name of the author nor the names
#   of its contributors may be used to endorse
#   or promote products derived from this software
#   without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
# OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
# OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
# AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
# EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

'''Intel HEX file format reader and converter.

@author     Alexander Belchenko (bialix AT ukr net)
@version    1.1
'''
from __future__ import division, print_function

from builtins import bytes
from builtins import str
from builtins import range
from past.builtins import basestring
from builtins import object
from past.utils import old_div
__docformat__ = "javadoc"

from array import array
from binascii import hexlify, unhexlify
from bisect import bisect_right
import os
import sys
from .bits import correctbytes


# the Python 2 integer types int and long have been unified in Python 3
if sys.version_info < (3,):
    integer_types = (int, long,)
else:
    integer_types = (int,)


class IntelHex(object):
    ''' Intel HEX file reader. '''

    def __init__(self, source=None):
        ''' Constructor. If source specified, object will be initialized
        with the contents of source. Otherwise the object will be empty.

        @param  source      source for initialization
                            (file name of HEX file, file object, addr dict or
                             other IntelHex object)
        '''
        #public members
        self.padding = 0x0FF
        # Start Address
        self.start_addr = None

        # private members
        self._buf = {}
        self._offset = 0

        if source is not None:
            if isinstance(source, basestring) or getattr(source, "read", None):
                # load hex file
                self.loadhex(source)
            elif isinstance(source, dict):
                self.fromdict(source)
            elif isinstance(source, IntelHex):
                self.padding = source.padding
                if source.start_addr:
                    self.start_addr = source.start_addr.copy()
                self._buf = source._buf.copy()
            else:
                raise ValueError("source: bad initializer type")

    def _decode_record(self, s, line=0):
        '''Decode one record of HEX file.

        @param  s       line with HEX record.
        @param  line    line number (for error messages).

        @raise  EndOfFile   if EOF record encountered.
        '''
        s = s.rstrip('\r\n')
        if not s:
            return          # empty line

        if s[0] == ':':
            try:
                bin = array('B', unhexlify(s[1:]))
            except TypeError:
                # this might be raised by unhexlify when odd hexascii digits
                raise HexRecordError(line=line)
            length = len(bin)
            if length < 5:
                raise HexRecordError(line=line)
        else:
            raise HexRecordError(line=line)

        record_length = bin[0]
        if length != (5 + record_length):
            raise RecordLengthError(line=line)

        addr = bin[1]*256 + bin[2]

        record_type = bin[3]
        if not (0 <= record_type <= 5):
            raise RecordTypeError(line=line)

        crc = sum(bin)
        crc &= 0x0FF
        if crc != 0:
            raise RecordChecksumError(line=line)

        if record_type == 0:
            # data record
            addr += self._offset
            for i in range(4, 4+record_length):
                if self._buf.get(addr, None) is not None:
                    raise AddressOverlapError(address=addr, line=line)
                self._buf[addr] = bin[i]
                addr += 1   # FIXME: addr should be wrapped 
                            # BUT after 02 record (at 64K boundary)
                            # and after 04 record (at 4G boundary)

        elif record_type == 1:
            # end of file record
            if record_length != 0:
                raise EOFRecordError(line=line)
            raise _EndOfFile

        elif record_type == 2:
            # Extended 8086 Segment Record
            if record_length != 2 or addr != 0:
                raise ExtendedSegmentAddressRecordError(line=line)
            self._offset = (bin[4]*256 + bin[5]) * 16

        elif record_type == 4:
            # Extended Linear Address Record
            if record_length != 2 or addr != 0:
                raise ExtendedLinearAddressRecordError(line=line)
            self._offset = (bin[4]*256 + bin[5]) * 65536

        elif record_type == 3:
            # Start Segment Address Record
            if record_length != 4 or addr != 0:
                raise StartSegmentAddressRecordError(line=line)
            if self.start_addr:
                raise DuplicateStartAddressRecordError(line=line)
            self.start_addr = {'CS': bin[4]*256 + bin[5],
                               'IP': bin[6]*256 + bin[7],
                              }

        elif record_type == 5:
            # Start Linear Address Record
            if record_length != 4 or addr != 0:
                raise StartLinearAddressRecordError(line=line)
            if self.start_addr:
                raise DuplicateStartAddressRecordError(line=line)
            self.start_addr = {'EIP': (bin[4]*16777216 +
                                       bin[5]*65536 +
                                       bin[6]*256 +
                                       bin[7]),
                              }

    def loadhexbytes(self, hbytes):
        """Load hex bytes into internal buffer.

        @param  hbytes          intelhex file in bytes
        """
        self._offset = 0
        line = 0

        decode = self._decode_record
        try:
            for s in fobj:
                line += 1
                decode(s, line)
        except _EndOfFile:
            pass

    def loadhex(self, fobj):
        """Load hex file into internal buffer. This is not necessary
        if object was initialized with source set. This will overwrite
        addresses if object was already initialized.

        @param  fobj        file name or file-like object
        """
        if getattr(fobj, "read", None) is None:
            fobj = open(fobj, "r")
            fclose = fobj.close
        else:
            fclose = None

        self._offset = 0
        line = 0

        try:
            decode = self._decode_record
            try:
                for s in fobj:
                    line += 1
                    decode(s, line)
            except _EndOfFile:
                pass
        finally:
            if fclose:
                fclose()

    def loadbin(self, fobj, offset=0):
        """Load bin file into internal buffer. Not needed if source set in
        constructor. This will overwrite addresses without warning
        if object was already initialized.

        @param  fobj        file name or file-like object
        @param  offset      starting address offset
        """
        fread = getattr(fobj, "read", None)
        if fread is None:
            f = open(fobj, "rb")
            fread = f.read
            fclose = f.close
        else:
            fclose = None

        try:
            for b in array('B', fread()):
                self._buf[offset] = b
                offset += 1
        finally:
            if fclose:
                fclose()

    def loadfile(self, fobj, format):
        """Load data file into internal buffer. Preferred wrapper over
        loadbin or loadhex.

        @param  fobj        file name or file-like object
        @param  format      file format ("hex" or "bin")
        """
        if format == "hex":
            self.loadhex(fobj)
        elif format == "bin":
            self.loadbin(fobj)
        else:
            raise ValueError('format should be either "hex" or "bin";'
                ' got %r instead' % format)

    # alias (to be consistent with method tofile)
    fromfile = loadfile

    def fromdict(self, dikt):
        """Load data from dictionary. Dictionary should contain int keys
        representing addresses. Values should be the data to be stored in
        those addresses in unsigned char form (i.e. not strings).
        The dictionary may contain the key, ``start_addr``
        to indicate the starting address of the data as described in README.

        The contents of the dict will be merged with this object and will
        overwrite any conflicts. This function is not necessary if the
        object was initialized with source specified.
        """
        s = dikt.copy()
        start_addr = s.get('start_addr')
        if 'start_addr' in s:
            del s['start_addr']
        for k in list(s.keys()):
            if type(k) not in integer_types or k < 0:
                raise ValueError('Source dictionary should have only int keys')
        self._buf.update(s)
        if start_addr is not None:
            self.start_addr = start_addr

    def _get_start_end(self, start=None, end=None):
        """Return default values for start and end if they are None
        """
        if start is None:
            start = min(self._buf.keys())
        if end is None:
            end = max(self._buf.keys())
        if start > end:
            start, end = end, start
        return start, end

    def tobinarray(self, start=None, end=None, pad=None):
        ''' Convert this object to binary form as array. If start and end 
        unspecified, they will be inferred from the data.
        @param  start   start address of output bytes.
        @param  end     end address of output bytes.
        @param  pad     fill empty spaces with this value
                        (if None used self.padding).
        @return         array of unsigned char data.
        '''
        if pad is None:
            pad = self.padding

        bin = array('B')

        if self._buf == {}:
            return bin

        start, end = self._get_start_end(start, end)

        for i in range(start, end+1):
            bin.append(self._buf.get(i, pad))

        return bin

    def tobinstr(self, start=None, end=None, pad=0xFF):
        ''' Convert to binary form and return as a string.
        @param  start   start address of output bytes.
        @param  end     end address of output bytes.
        @param  pad     fill empty spaces with this value
                        (if None used self.padding).
        @return         string of binary data.
        '''
        return self.tobinarray(start, end, pad).tostring()

    def tobinfile(self, fobj, start=None, end=None, pad=0xFF):
        '''Convert to binary and write to file.

        @param  fobj    file name or file object for writing output bytes.
        @param  start   start address of output bytes.
        @param  end     end address of output bytes.
        @param  pad     fill empty spaces with this value
                        (if None used self.padding).
        '''
        if getattr(fobj, "write", None) is None:
            fobj = open(fobj, "wb")
            close_fd = True
        else:
            close_fd = False

        fobj.write(self.tobinstr(start, end, pad))

        if close_fd:
            fobj.close()

    def todict(self):
        '''Convert to python dictionary.

        @return         dict suitable for initializing another IntelHex object.
        '''
        r = {}
        r.update(self._buf)
        if self.start_addr:
            r['start_addr'] = self.start_addr
        return r

    def addresses(self):
        '''Returns all used addresses in sorted order.
        @return         list of occupied data addresses in sorted order. 
        '''
        aa = list(self._buf.keys())
        aa.sort()
        return aa

    def minaddr(self):
        '''Get minimal address of HEX content.
        @return         minimal address or None if no data
        '''
        aa = list(self._buf.keys())
        if aa == []:
            return None
        else:
            return min(aa)

    def maxaddr(self):
        '''Get maximal address of HEX content.
        @return         maximal address or None if no data
        '''
        aa = list(self._buf.keys())
        if aa == []:
            return None
        else:
            return max(aa)

    def __getitem__(self, addr):
        ''' Get requested byte from address.
        @param  addr    address of byte.
        @return         byte if address exists in HEX file, or self.padding
                        if no data found.
        '''
        t = type(addr)
        if t in integer_types:
            if addr < 0:
                raise TypeError('Address should be >= 0.')
            return self._buf.get(addr, self.padding)
        elif t == slice:
            addresses = list(self._buf.keys())
            ih = IntelHex()
            if addresses:
                addresses.sort()
                start = addr.start or addresses[0]
                stop = addr.stop or (addresses[-1]+1)
                step = addr.step or 1
                for i in range(start, stop, step):
                    x = self._buf.get(i)
                    if x is not None:
                        ih[i] = x
            return ih
        else:
            raise TypeError('Address has unsupported type: %s' % t)

    def __setitem__(self, addr, byte):
        """Set byte at address."""
        t = type(addr)
        if t in integer_types:
            if addr < 0:
                raise TypeError('Address should be >= 0.')
            self._buf[addr] = byte
        elif t == slice:
            addresses = list(self._buf.keys())
            if not isinstance(byte, (list, tuple)):
                raise ValueError('Slice operation expects sequence of bytes')
            start = addr.start
            stop = addr.stop
            step = addr.step or 1
            if None not in (start, stop):
                ra = list(range(start, stop, step))
                if len(ra) != len(byte):
                    raise ValueError('Length of bytes sequence does not match '
                        'address range')
            elif (start, stop) == (None, None):
                raise TypeError('Unsupported address range')
            elif start is None:
                start = stop - len(byte)
            elif stop is None:
                stop = start + len(byte)
            if start < 0:
                raise TypeError('start address cannot be negative')
            if stop < 0:
                raise TypeError('stop address cannot be negative')
            j = 0
            for i in range(start, stop, step):
                self._buf[i] = byte[j]
                j += 1
        else:
            raise TypeError('Address has unsupported type: %s' % t)

    def __delitem__(self, addr):
        """Delete byte at address."""
        t = type(addr)
        if t in integer_types:
            if addr < 0:
                raise TypeError('Address should be >= 0.')
            del self._buf[addr]
        elif t == slice:
            addresses = list(self._buf.keys())
            if addresses:
                addresses.sort()
                start = addr.start or addresses[0]
                stop = addr.stop or (addresses[-1]+1)
                step = addr.step or 1
                for i in range(start, stop, step):
                    x = self._buf.get(i)
                    if x is not None:
                        del self._buf[i]
        else:
            raise TypeError('Address has unsupported type: %s' % t)

    def __len__(self):
        """Return count of bytes with real values."""
        return len(list(self._buf.keys()))

    def write_hex_file(self, f, write_start_addr=True):
        """Write data to file f in HEX format.

        @param  f                   filename or file-like object for writing
        @param  write_start_addr    enable or disable writing start address
                                    record to file (enabled by default).
                                    If there is no start address in obj, nothing
                                    will be written regardless of this setting.
        """
        fwrite = getattr(f, "write", None)
        if fwrite:
            fobj = f
            fclose = None
        else:
            fobj = open(f, 'w')
            fwrite = fobj.write
            fclose = fobj.close

        # Translation table for uppercasing hex ascii string.
        # timeit shows that using hexstr.translate(table)
        # is faster than hexstr.upper():
        # 0.452ms vs. 0.652ms (translate vs. upper)
        table = b''.join(correctbytes(i).upper() for  i in range(256))

        # start address record if any
        if self.start_addr and write_start_addr:
            keys = list(self.start_addr.keys())
            keys.sort()
            bin = array('B', b'\0'*9)
            if keys == ['CS','IP']:
                # Start Segment Address Record
                bin[0] = 4      # reclen
                bin[1] = 0      # offset msb
                bin[2] = 0      # offset lsb
                bin[3] = 3      # rectyp
                cs = self.start_addr['CS']
                bin[4] = (cs >> 8) & 0x0FF
                bin[5] = cs & 0x0FF
                ip = self.start_addr['IP']
                bin[6] = (ip >> 8) & 0x0FF
                bin[7] = ip & 0x0FF
                bin[8] = (-sum(bin)) & 0x0FF    # chksum
                fwrite(b':' + hexlify(bin.tostring()).translate(table) + b'\n')
            elif keys == ['EIP']:
                # Start Linear Address Record
                bin[0] = 4      # reclen
                bin[1] = 0      # offset msb
                bin[2] = 0      # offset lsb
                bin[3] = 5      # rectyp
                eip = self.start_addr['EIP']
                bin[4] = (eip >> 24) & 0x0FF
                bin[5] = (eip >> 16) & 0x0FF
                bin[6] = (eip >> 8) & 0x0FF
                bin[7] = eip & 0x0FF
                bin[8] = (-sum(bin)) & 0x0FF    # chksum
                fwrite(b':' + hexlify(bin.tostring()).translate(table) + b'\n')
            else:
                if fclose:
                    fclose()
                raise InvalidStartAddressValueError(start_addr=self.start_addr)

        # data
        addresses = list(self._buf.keys())
        addresses.sort()
        addr_len = len(addresses)
        if addr_len:
            minaddr = addresses[0]
            maxaddr = addresses[-1]
    
            if maxaddr > 65535:
                need_offset_record = True
            else:
                need_offset_record = False
            high_ofs = 0

            cur_addr = minaddr
            cur_ix = 0

            while cur_addr <= maxaddr:
                if need_offset_record:
                    bin = array('B', b'\0'*7)
                    bin[0] = 2      # reclen
                    bin[1] = 0      # offset msb
                    bin[2] = 0      # offset lsb
                    bin[3] = 4      # rectyp
                    high_ofs = int(old_div(cur_addr,65536))
                    bytes = divmod(high_ofs, 256)
                    bin[4] = bytes[0]   # msb of high_ofs
                    bin[5] = bytes[1]   # lsb of high_ofs
                    bin[6] = (-sum(bin)) & 0x0FF    # chksum
                    fwrite(b':' + hexlify(bin.tostring()).translate(table) + b'\n')

                while True:
                    # produce one record
                    low_addr = cur_addr & 0x0FFFF
                    # chain_len off by 1
                    chain_len = min(15, 65535-low_addr, maxaddr-cur_addr)

                    # search continuous chain
                    stop_addr = cur_addr + chain_len
                    if chain_len:
                        ix = bisect_right(addresses, stop_addr,
                                          cur_ix,
                                          min(cur_ix+chain_len+1, addr_len))
                        chain_len = ix - cur_ix     # real chain_len
                        # there could be small holes in the chain
                        # but we will catch them by try-except later
                        # so for big continuous files we will work
                        # at maximum possible speed
                    else:
                        chain_len = 1               # real chain_len

                    bin = array('B', b'\0'*(5+chain_len))
                    bytes = divmod(low_addr, 256)
                    bin[1] = bytes[0]   # msb of low_addr
                    bin[2] = bytes[1]   # lsb of low_addr
                    bin[3] = 0          # rectype
                    try:    # if there is small holes we'll catch them
                        for i in range(chain_len):
                            bin[4+i] = self._buf[cur_addr+i]
                    except KeyError:
                        # we catch a hole so we should shrink the chain
                        chain_len = i
                        bin = bin[:5+i]
                    bin[0] = chain_len
                    bin[4+chain_len] = (-sum(bin)) & 0x0FF    # chksum
                    fwrite(':' + hexlify(bin.tostring()).translate(table).decode('latin1') + '\n')

                    # adjust cur_addr/cur_ix
                    cur_ix += chain_len
                    if cur_ix < addr_len:
                        cur_addr = addresses[cur_ix]
                    else:
                        cur_addr = maxaddr + 1
                        break
                    high_addr = int(old_div(cur_addr,65536))
                    if high_addr > high_ofs:
                        break

        # end-of-file record
        fwrite(":00000001FF\n")
        if fclose:
            fclose()

    def tofile(self, fobj, format):
        """Write data to hex or bin file. Preferred method over tobin or tohex.

        @param  fobj        file name or file-like object
        @param  format      file format ("hex" or "bin")
        """
        if format == 'hex':
            self.write_hex_file(fobj)
        elif format == 'bin':
            self.tobinfile(fobj)
        else:
            raise ValueError('format should be either "hex" or "bin";'
                ' got %r instead' % format)

    def gets(self, addr, length):
        """Get string of bytes from given address. If any entries are blank
        from addr through addr+length, a NotEnoughDataError exception will
        be raised. Padding is not used."""
        a = array('B', b'\0'*length)
        try:
            for i in range(length):
                a[i] = self._buf[addr+i]
        except KeyError:
            raise NotEnoughDataError(address=addr, length=length)
        return a.tostring()

    def puts(self, addr, s):
        """Put string of bytes at given address. Will overwrite any previous
        entries.
        """
        a = array('B', bytes(s, 'latin1'))
        for i in range(len(s)):
            self._buf[addr+i] = a[i]

    def getsz(self, addr):
        """Get zero-terminated string from given address. Will raise 
        NotEnoughDataError exception if a hole is encountered before a 0.
        """
        i = 0
        try:
            while True:
                if self._buf[addr+i] == 0:
                    break
                i += 1
        except KeyError:
            raise NotEnoughDataError(msg=('Bad access at 0x%X: '
                'not enough data to read zero-terminated string') % addr)
        return self.gets(addr, i)

    def putsz(self, addr, s):
        """Put string in object at addr and append terminating zero at end."""
        self.puts(addr, s)
        self._buf[addr+len(s)] = 0

    def dump(self, tofile=None):
        """Dump object content to specified file or to stdout if None. Format
        is a hexdump with some header information at the beginning, addresses
        on the left, and data on right.

        @param  tofile        file-like object to dump to
        """

        if tofile is None:
            import sys
            tofile = sys.stdout
        # start addr possibly
        if self.start_addr is not None:
            cs = self.start_addr.get('CS')
            ip = self.start_addr.get('IP')
            eip = self.start_addr.get('EIP')
            if eip is not None and cs is None and ip is None:
                tofile.write('EIP = 0x%08X\n' % eip)
            elif eip is None and cs is not None and ip is not None:
                tofile.write('CS = 0x%04X, IP = 0x%04X\n' % (cs, ip))
            else:
                tofile.write('start_addr = %r\n' % start_addr)
        # actual data
        addresses = list(self._buf.keys())
        if addresses:
            addresses.sort()
            minaddr = addresses[0]
            maxaddr = addresses[-1]
            startaddr = int(old_div(minaddr,16))*16
            endaddr = int(old_div(maxaddr,16)+1)*16
            maxdigits = max(len(str(endaddr)), 4)
            templa = '%%0%dX' % maxdigits
            range16 = list(range(16))
            for i in range(startaddr, endaddr, 16):
                tofile.write(templa % i)
                tofile.write(' ')
                s = []
                for j in range16:
                    x = self._buf.get(i+j)
                    if x is not None:
                        tofile.write(' %02X' % x)
                        if 32 <= x < 128:
                            s.append(correctbytes(x))
                        else:
                            s.append('.')
                    else:
                        tofile.write(' --')
                        s.append(' ')
                tofile.write('  |' + ''.join(s) + '|\n')

    def merge(this, other, overlap='error'):
        """Merge content of other IntelHex object to this object.
        @param  other   other IntelHex object.
        @param  overlap action on overlap of data or starting addr:
                        - error: raising OverlapError;
                        - ignore: ignore other data and keep this data
                                  in overlapping region;
                        - replace: replace this data with other data
                                  in overlapping region.

        @raise  TypeError       if other is not instance of IntelHex
        @raise  ValueError      if other is the same object as this
        @raise  ValueError      if overlap argument has incorrect value
        @raise  AddressOverlapError    on overlapped data
        """
        # check args
        if not isinstance(other, IntelHex):
            raise TypeError('other should be IntelHex object')
        if other is this:
            raise ValueError("Can't merge itself")
        if overlap not in ('error', 'ignore', 'replace'):
            raise ValueError("overlap argument should be either "
                "'error', 'ignore' or 'replace'")
        # merge data
        this_buf = this._buf
        other_buf = other._buf
        for i in other_buf:
            if i in this_buf:
                if overlap == 'error':
                    raise AddressOverlapError(
                        'Data overlapped at address 0x%X' % i)
                elif overlap == 'ignore':
                    continue
            this_buf[i] = other_buf[i]
        # merge start_addr
        if this.start_addr != other.start_addr:
            if this.start_addr is None:     # set start addr from other
                this.start_addr = other.start_addr
            elif other.start_addr is None:  # keep this start addr
                pass
            else:                           # conflict
                if overlap == 'error':
                    raise AddressOverlapError(
                        'Starting addresses are different')
                elif overlap == 'replace':
                    this.start_addr = other.start_addr
#/IntelHex


class IntelHex16bit(IntelHex):
    """Access to data as 16-bit words."""

    def __init__(self, source):
        """Construct class from HEX file
        or from instance of ordinary IntelHex class. If IntelHex object
        is passed as source, the original IntelHex object should not be used
        again because this class will alter it. This class leaves padding
        alone unless it was precisely 0xFF. In that instance it is sign
        extended to 0xFFFF.

        @param  source  file name of HEX file or file object
                        or instance of ordinary IntelHex class.
                        Will also accept dictionary from todict method.
        """
        if isinstance(source, IntelHex):
            # from ihex8
            self.padding = source.padding
            # private members
            self._buf = source._buf
            self._offset = source._offset
        else:
            IntelHex.__init__(self, source)

        if self.padding == 0x0FF:
            self.padding = 0x0FFFF

    def __getitem__(self, addr16):
        """Get 16-bit word from address.
        Raise error if only one byte from the pair is set.
        We assume a Little Endian interpretation of the hex file.

        @param  addr16  address of word (addr8 = 2 * addr16).
        @return         word if bytes exists in HEX file, or self.padding
                        if no data found.
        """
        addr1 = addr16 * 2
        addr2 = addr1 + 1
        byte1 = self._buf.get(addr1, None)
        byte2 = self._buf.get(addr2, None)

        if byte1 != None and byte2 != None:
            return byte1 | (byte2 << 8)     # low endian

        if byte1 == None and byte2 == None:
            return self.padding

        raise BadAccess16bit(address=addr16)

    def __setitem__(self, addr16, word):
        """Sets the address at addr16 to word assuming Little Endian mode.
        """
        addr_byte = addr16 * 2
        bytes = divmod(word, 256)
        self._buf[addr_byte] = bytes[1]
        self._buf[addr_byte+1] = bytes[0]

    def minaddr(self):
        '''Get minimal address of HEX content in 16-bit mode.

        @return         minimal address used in this object 
        '''
        aa = list(self._buf.keys())
        if aa == []:
            return 0
        else:
            return old_div(min(aa),2)

    def maxaddr(self):
        '''Get maximal address of HEX content in 16-bit mode.

        @return         maximal address used in this object 
        '''
        aa = list(self._buf.keys())
        if aa == []:
            return 0
        else:
            return old_div(max(aa),2)

#/class IntelHex16bit


def hex2bin(fin, fout, start=None, end=None, size=None, pad=0xFF):
    """Hex-to-Bin converter engine.
    @return     0   if all OK

    @param  fin     input hex file (filename or file-like object)
    @param  fout    output bin file (filename or file-like object)
    @param  start   start of address range (optional)
    @param  end     end of address range (optional)
    @param  size    size of resulting file (in bytes) (optional)
    @param  pad     padding byte (optional)
    """
    try:
        h = IntelHex(fin)
    except HexReaderError as e:
        print("ERROR: bad HEX file: %s" % str(e))
        return 1

    # start, end, size
    if size != None and size != 0:
        if end == None:
            if start == None:
                start = h.minaddr()
            end = start + size - 1
        else:
            if (end+1) >= size:
                start = end + 1 - size
            else:
                start = 0

    try:
        h.tobinfile(fout, start, end, pad)
    except IOError as e:
        print("ERROR: Could not write to file: %s: %s" % (fout, str(e)))
        return 1

    return 0
#/def hex2bin


def bin2hex(fin, fout, offset=0):
    """Simple bin-to-hex converter.
    @return     0   if all OK

    @param  fin     input bin file (filename or file-like object)
    @param  fout    output hex file (filename or file-like object)
    @param  offset  starting address offset for loading bin
    """
    h = IntelHex()
    try:
        h.loadbin(fin, offset)
    except IOError as e:
        print('ERROR: unable to load bin file:', str(e))
        return 1

    try:
        h.tofile(fout, format='hex')
    except IOError as e:
        print("ERROR: Could not write to file: %s: %s" % (fout, str(e)))
        return 1

    return 0
#/def bin2hex


class Record(object):
    """Helper methods to build valid ihex records."""

    def _from_bytes(bytes):
        """Takes a list of bytes, computes the checksum, and outputs the entire
        record as a string. bytes should be the hex record without the colon
        or final checksum.

        @param  bytes   list of byte values so far to pack into record.
        @return         String representation of one HEX record
        """
        assert len(bytes) >= 4
        # calculate checksum
        s = (-sum(bytes)) & 0x0FF
        bin = array('B', bytes + [s])
        return b':' + hexlify(bin.tostring()).upper()
    _from_bytes = staticmethod(_from_bytes)

    def data(offset, bytes):
        """Return Data record. This constructs the full record, including
        the length information, the record type (0x00), the
        checksum, and the offset.

        @param  offset  load offset of first byte.
        @param  bytes   list of byte values to pack into record.

        @return         String representation of one HEX record
        """
        assert 0 <= offset < 65536
        assert 0 < len(bytes) < 256
        b = [len(bytes), (offset>>8)&0x0FF, offset&0x0FF, 0x00] + bytes
        return Record._from_bytes(b)
    data = staticmethod(data)

    def eof():
        """Return End of File record as a string.
        @return         String representation of Intel Hex EOF record 
        """
        return ':00000001FF'
    eof = staticmethod(eof)

    def extended_segment_address(usba):
        """Return Extended Segment Address Record.
        @param  usba     Upper Segment Base Address.

        @return         String representation of Intel Hex USBA record.
        """
        b = [2, 0, 0, 0x02, (usba>>8)&0x0FF, usba&0x0FF]
        return Record._from_bytes(b)
    extended_segment_address = staticmethod(extended_segment_address)

    def start_segment_address(cs, ip):
        """Return Start Segment Address Record.
        @param  cs      16-bit value for CS register.
        @param  ip      16-bit value for IP register.

        @return         String representation of Intel Hex SSA record.
        """
        b = [4, 0, 0, 0x03, (cs>>8)&0x0FF, cs&0x0FF,
             (ip>>8)&0x0FF, ip&0x0FF]
        return Record._from_bytes(b)
    start_segment_address = staticmethod(start_segment_address)

    def extended_linear_address(ulba):
        """Return Extended Linear Address Record.
        @param  ulba    Upper Linear Base Address.

        @return         String representation of Intel Hex ELA record.
        """
        b = [2, 0, 0, 0x04, (ulba>>8)&0x0FF, ulba&0x0FF]
        return Record._from_bytes(b)
    extended_linear_address = staticmethod(extended_linear_address)

    def start_linear_address(eip):
        """Return Start Linear Address Record.
        @param  eip     32-bit linear address for the EIP register.

        @return         String representation of Intel Hex SLA record.
        """
        b = [4, 0, 0, 0x05, (eip>>24)&0x0FF, (eip>>16)&0x0FF,
             (eip>>8)&0x0FF, eip&0x0FF]
        return Record._from_bytes(b)
    start_linear_address = staticmethod(start_linear_address)


class _BadFileNotation(Exception):
    """Special error class to use with _get_file_and_addr_range."""
    pass

def _get_file_and_addr_range(s, _support_drive_letter=None):
    """Special method for hexmerge.py script to split file notation
    into 3 parts: (filename, start, end)

    @raise _BadFileNotation  when string cannot be safely split.
    """
    if _support_drive_letter is None:
        _support_drive_letter = (os.name == 'nt')
    drive = ''
    if _support_drive_letter:
        if s[1:2] == ':' and s[0].upper() in ''.join([correctbytes(i) for i in range(ord('A'), ord('Z')+1)]):
            drive = s[:2]
            s = s[2:]
    parts = s.split(':')
    n = len(parts)
    if n == 1:
        fname = parts[0]
        fstart = None
        fend = None
    elif n != 3:
        raise _BadFileNotation
    else:
        fname = parts[0]
        def ascii_hex_to_int(ascii):
            if ascii is not None:
                try:
                    return int(ascii, 16)
                except ValueError:
                    raise _BadFileNotation
            return ascii
        fstart = ascii_hex_to_int(parts[1] or None)
        fend = ascii_hex_to_int(parts[2] or None)
    return drive+fname, fstart, fend


##
# IntelHex Errors Hierarchy:
#
#  IntelHexError    - basic error
#       HexReaderError  - general hex reader error
#           AddressOverlapError - data for the same address overlap
#           HexRecordError      - hex record decoder base error
#               RecordLengthError    - record has invalid length
#               RecordTypeError      - record has invalid type (RECTYP)
#               RecordChecksumError  - record checksum mismatch
#               EOFRecordError              - invalid EOF record (type 01)
#               ExtendedAddressRecordError  - extended address record base error
#                   ExtendedSegmentAddressRecordError   - invalid extended segment address record (type 02)
#                   ExtendedLinearAddressRecordError    - invalid extended linear address record (type 04)
#               StartAddressRecordError     - start address record base error
#                   StartSegmentAddressRecordError      - invalid start segment address record (type 03)
#                   StartLinearAddressRecordError       - invalid start linear address record (type 05)
#                   DuplicateStartAddressRecordError    - start address record appears twice
#                   InvalidStartAddressValueError       - invalid value of start addr record
#       _EndOfFile  - it's not real error, used internally by hex reader as signal that EOF record found
#       BadAccess16bit - not enough data to read 16 bit value (deprecated, see NotEnoughDataError)
#       NotEnoughDataError - not enough data to read N contiguous bytes

class IntelHexError(Exception):
    '''Base Exception class for IntelHex module'''

    _fmt = 'IntelHex base error'   #: format string

    def __init__(self, msg=None, **kw):
        """Initialize the Exception with the given message.
        """
        self.msg = msg
        for key, value in list(kw.items()):
            setattr(self, key, value)

    def __str__(self):
        """Return the message in this Exception."""
        if self.msg:
            return self.msg
        try:
            return self._fmt % self.__dict__
        except (NameError, ValueError, KeyError) as e:
            return 'Unprintable exception %s: %s' \
                % (self.__class__.__name__, str(e))

class _EndOfFile(IntelHexError):
    """Used for internal needs only."""
    _fmt = 'EOF record reached -- signal to stop read file'

class HexReaderError(IntelHexError):
    _fmt = 'Hex reader base error'

class AddressOverlapError(HexReaderError):
    _fmt = 'Hex file has data overlap at address 0x%(address)X on line %(line)d'

# class NotAHexFileError was removed in trunk.revno.54 because it's not used


class HexRecordError(HexReaderError):
    _fmt = 'Hex file contains invalid record at line %(line)d'


class RecordLengthError(HexRecordError):
    _fmt = 'Record at line %(line)d has invalid length'

class RecordTypeError(HexRecordError):
    _fmt = 'Record at line %(line)d has invalid record type'

class RecordChecksumError(HexRecordError):
    _fmt = 'Record at line %(line)d has invalid checksum'

class EOFRecordError(HexRecordError):
    _fmt = 'File has invalid End-of-File record'


class ExtendedAddressRecordError(HexRecordError):
    _fmt = 'Base class for extended address exceptions'

class ExtendedSegmentAddressRecordError(ExtendedAddressRecordError):
    _fmt = 'Invalid Extended Segment Address Record at line %(line)d'

class ExtendedLinearAddressRecordError(ExtendedAddressRecordError):
    _fmt = 'Invalid Extended Linear Address Record at line %(line)d'


class StartAddressRecordError(HexRecordError):
    _fmt = 'Base class for start address exceptions'

class StartSegmentAddressRecordError(StartAddressRecordError):
    _fmt = 'Invalid Start Segment Address Record at line %(line)d'

class StartLinearAddressRecordError(StartAddressRecordError):
    _fmt = 'Invalid Start Linear Address Record at line %(line)d'

class DuplicateStartAddressRecordError(StartAddressRecordError):
    _fmt = 'Start Address Record appears twice at line %(line)d'

class InvalidStartAddressValueError(StartAddressRecordError):
    _fmt = 'Invalid start address value: %(start_addr)s'


class NotEnoughDataError(IntelHexError):
    _fmt = ('Bad access at 0x%(address)X: '
            'not enough data to read %(length)d contiguous bytes')

class BadAccess16bit(NotEnoughDataError):
    _fmt = 'Bad access at 0x%(address)X: not enough data to read 16 bit value'
