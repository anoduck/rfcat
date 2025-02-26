from binascii import hexlify
import sys
import struct

fmtsLSB = [None, b"B", b"<H", b"<I", b"<I", b"<Q", b"<Q", b"<Q", b"<Q"]
fmtsMSB = [None, b"B", b">H", b">I", b">I", b">Q", b">Q", b">Q", b">Q"]
sizes = [ 0, 1, 2, 4, 4, 8, 8, 8, 8]
masks = [ (1<<(8*i))-1 for i in range(9) ]

PYVER = int(sys.version[0])
def correctbytes(val):
    global PYVER

    if PYVER == 2:
        return chr(val)

    return bytes([val])

def wtfo(string):
    outstr = []
    bitlen = len(outstr) * 8
    for x in range(8):
        outstr.append(shiftString(string, x))

    string = strBitReverse(string)
    for x in range(8):
        outstr.append(shiftString(string, x))

    return outstr


def ord23(thing):
    if PYVER == 2:
        return ord(thing)
    return thing


def strBitReverse(string:bytes):
    # FIXME: this is really dependent upon python's number system.  large strings will not convert well.  
    # FIXME: break up array of 8-bit numbers and bit-swap in the array
    num = 0
    bits = len(string)*8
    # convert to MSB number
    for x in range(len(string)):
        ch = string[x]
        #num |= (ord(ch:ch+1)<<(8*x))        # this is LSB
        num <<= 8
        num |= ch

    print(hex(num))
    rnum = bitReverse(num, bits)
    print(hex(rnum))

    # convert back from MSB number to string
    out = []
    for x in range(len(string)):
        out.append(correctbytes(rnum&0xff))
        rnum >>= 8
    out.reverse()
    print(b''.join(out))
    return b''.join(out)

def strXorMSB(string, xorval, size):
    '''
    lsb
    pads end of string with 00
    '''
    out = []
    strlen = len(string)
    string += b"\x00" * sizes[size]

    for idx in range(0, strlen, size):
        tempstr = string[idx:idx+sizes[size]]
        temp, = struct.unpack( fmtsMSB[size], tempstr )
        temp ^= xorval
        temp &= masks[size]
        tempstr = struct.pack( fmtsMSB[size], temp )[-size:]
        out.append(tempstr)
    return b''.join(out)

        
        

def bitReverse(num, bitcnt):
    newnum = 0
    for idx in range(bitcnt):
        newnum <<= 1
        newnum |= num&1
        num    >>= 1
    return newnum

def shiftString(string, bits):
    '''
    In Python3, use bytes instead of a str
    '''
    carry = 0
    news = []
    for x in range(len(string)-1):
        newc = ((string[x] << bits) + (string[x+1] >> (8-bits))) & 0xff
        news.append(b"%c"%newc)
    newc = (ord23(string[-1])<<bits) & 0xff
    news.append(b"%c"%newc)
    return b"".join(news)

def getNextByte_feedbackRegister7bitsMSB():
    '''
    this returns a byte of a 7-bit feedback register stemming off bits 4 and 7
    the register is 7 bits long, but we return a more usable 8bits (ie. 
    '''
    global fbRegister

    retval = 0
    for x in range(8):      #MSB, 
        retval <<= 1
        retval |= (fbRegister >> 6)         # start with bit 7
        nb = ( ( fbRegister>>3) ^ (fbRegister>>6)) &1 
        fbRegister = ( ( fbRegister << 1 )   |   nb ) & 0x7f # do shifting
        #print("retval: %x  fbRegister: %x  bit7: %x  nb: %x" % (retval, fbRegister, (fbRegister>>6), nb))

    return retval

def getNextByte_feedbackRegister7bitsLSB():
    '''
    this returns a byte of a 7-bit feedback register stemming off bits 4 and 7
    the register is 7 bits long, but we return a more usable 8bits (ie. 
    '''
    global fbRegister

    retval = 0
    for x in range(8):      #MSB, 
        retval >>= 1
        retval |= ((fbRegister << 1)&0x80)         # start with bit 7

        nb = ( ( fbRegister>>3) ^ (fbRegister>>6)) &1 
        fbRegister = ( ( fbRegister << 1 )   |   nb ) & 0x7f # do shifting
        #print("retval: %x  fbRegister: %x  bit7: %x  nb: %x" % (retval, fbRegister, (fbRegister>>6), nb))

    return retval


def whitenData(data, seed=0xffff, getNextByte=getNextByte_feedbackRegister7bitsMSB):
    global fbRegister
    fbRegister = seed

    carry = 0
    news = []
    for x in range(len(data)-1):
        newc = ((ord23(data[x]) ^ getNextByte() ) & 0xff)
        news.append(b"%c" % newc)
    return b"".join(news)

def findSyncWord(byts, sensitivity=4, minpreamble=2): 
        '''
        seek SyncWords from a raw bitstream.  
        assumes we capture at least two (more likely 3 or more) preamble bytes
        '''
        possDwords = []
        # find the preamble (if any)
        while True:         # keep searching through string until we don't find any more preamble bits to pick on
            sbyts = byts
            pidx_aa = byts.find(b"\xaa"*minpreamble)
            pidx_55 = byts.find(b"\x55"*minpreamble)
            if -1 in (pidx_aa, pidx_55):
                pidx = max(pidx_aa, pidx_55)
            else:
                pidx = min(pidx_aa, pidx_55)

            if pidx == pidx_55:
                byts = shiftString(byts, 1)

            if pidx == -1:
                return possDwords
            
            # chop off the nonsense before the preamble
            sbyts = byts[pidx:]
            #print("sbyts: %s" % repr(sbyts))
            
            # find the definite end of the preamble (ie. it may be sooner, but we know this is the end)
            #print("sbyts[0]: %x" % sbyts[0])
            while (sbyts[0] == 0xaa and len(sbyts)>2):
                #print("... trimming 1 byte")
                sbyts = sbyts[1:]

            # slow trimming
            while (sbyts[0] & 0xc0 == 0xa0 and len(sbyts) > 2):
                #print("... slow trimming")
                byts = shiftString(byts, 2)
            
            #print("sbyts(post front trim): %s" % repr(sbyts))
            # now we look at the next 16 bits to narrow the possibilities to 8
            # at this point we have no hints at bit-alignment aside from 0xaa vs 0x55
            dwbits, = struct.unpack(b">H", sbyts[:2])
            #print("sbyts: %s" % repr(sbyts))
            #print("dwbits: %x" % (dwbits))
            if len(sbyts)>=3:
                bitcnt = 0
                #  bits1 =      aaaaaaaaaaaaaaaabbbbbbbbbbbbbbbb
                #  bits2 =                      bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
                bits1, = struct.unpack(b">H", sbyts[:2])
                bits1 = bits1 | (ord(b'\xaa') << 16)
                bits1 = bits1 | (ord(b'\xaa') << 24)
                bits1 <<= 8
                bits1 |= sbyts[2]
                #print("bits: %x" % (bits1))

                bit = (5 * 8) - 2  # bytes times bits/byte: 5bytes * 8 bits -2 (for what we're checking)
                while (bits1 & (3<<bit) == (2<<bit)) and bit > 16:
                    bit -= 2
                #print("bit = %d" % bit)
                bits1 >>= (bit-16)
                #while (bits1 & 0x30000 != 0x20000): # now we align the end of the 101010 pattern with the beginning of the dword
                #    bits1 >>= 2
                #print("bits: %x" % (bits1))
                
                bitcount = min( 2 * sensitivity, 17 ) 
                for frontbits in range( bitcount ):            # with so many bit-inverted systems, let's not assume we know anything about the bit-arrangement.  \x55\x55 could be a perfectly reasonable preamble.
                    poss = (bits1 >> frontbits) & 0xffff
                    #print("poss (%x >> %d): %x" % (bits1, frontbits, poss))
                    if poss not in possDwords:
                        possDwords.append(poss)
            byts = byts[pidx+1:]
        
        return possDwords

def findSyncWordDoubled(byts, sensitivity=4, minpreamble=2): 
    possDwords = []

    while True:         # keep searching through string until we don't find any more preamble bits to pick on
        # find the preamble (if any)
        bitoff = 0

        pidx_aa = byts.find(b"\xaa"*minpreamble)
        pidx_55 = byts.find(b"\x55"*minpreamble)
        if -1 in (pidx_aa, pidx_55):
            pidx = max(pidx_aa, pidx_55)
        else:
            pidx = min(pidx_aa, pidx_55)

        if pidx == pidx_55:
            bitoff = 1

        elif pidx == -1:
            return []


        # chop off the nonsense before the preamble
        byts = byts[pidx:]

        # find the definite end of the preamble (ie. it may be sooner, but we know this is the end)
        while (byts[0] == (0xaa, 0x55)[bitoff] and len(byts)>2):
            byts = byts[1:]

        # now we look at the next 16 bits to narrow the possibilities to 8
        # at this point we have no hints at bit-alignment
        dwbits, = struct.unpack(b">H", byts[:2])
        if len(byts)>=5:
            bitcnt = 0
            #  bits1 =      aaaaaaaaaaaaaaaabbbbbbbbbbbbbbbb
            #  bits2 =                      bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
            bits1, = struct.unpack(b">H", byts[:2])
            bits1 = bits1 | (((0xaa, 0x55)[bitoff]) << 16)
            bits1 = bits1 | (((0xaa, 0x55)[bitoff]) << 24)
            bits1 <<= 8
            bits1 |= byts[2]
            bits1 >>= bitoff

            bits2, = struct.unpack(b">L", byts[:4])
            bits2 <<= 8
            bits2 |= byts[4]
            bits2 >>= bitoff
            

            frontbits = 0
            for frontbits in range(16, 40, 2):    #FIXME: if this doesn't work, try 16, then 18+frontbits
                dwb1 = (bits1 >> (frontbits)) & 3
                dwb2 = (bits2 >> (frontbits)) & 3
                print("\tfrontbits: %d \t\t dwb1: %s dwb2: %s" % (frontbits, bin(bits1 >> (frontbits)), bin(bits2 >> (frontbits))))
                if dwb2 != dwb1:
                    break

            # frontbits now represents our unknowns...  let's go from the other side now
            for tailbits in range(16, -1, -2):
                dwb1 = (bits1 >> (tailbits)) & 3
                dwb2 = (bits2 >> (tailbits)) & 3
                print("\ttailbits: %d\t\t dwb1: %s dwb2: %s" % (tailbits, bin(bits1 >> (tailbits)), bin(bits2 >> (tailbits))))
                if dwb2 != dwb1:
                    tailbits += 2
                    break

            # now, if we have a double syncword, iinm, tailbits + frontbits >= 16
            print("frontbits: %d\t\t tailbits: %d, bits: %s " % (frontbits, tailbits, bin((bits2>>tailbits & 0xffffffff))))
            if (frontbits + tailbits >= 16):
                tbits = bits2 >> (tailbits&0xffff)
                tbits &= (0xffffffff)
                print("tbits: %x" % tbits)

                poss = tbits&0xffffffff
                if poss not in possDwords:
                    possDwords.append(poss)
            else:
                pass
                # FIXME: what if we *don't* have a double-sync word?  then we stop at AAblah or 55blah and take the next word?

            possDwords.reverse()
        return possDwords


def getBit(data, bit):
    idx = bit // 8
    bidx = bit % 8
    char = data[idx]
    return (char>>(7-bidx)) & 1



def detectRepeatPatterns(data:bytes, size=64, minEntropy=.07):
    #FIXME: convert bytes to bit arrays before comparing.
    patterns = []
    c1 = 0
    c2 = 0
    d1 = 0
    p1 = 0
    mask = (1<<size) - 1
    bitlen = 8*len(data)

    while p1 < (bitlen-size-8):
        d1 <<= 1
        d1 |= getBit(data, p1)
        d1 &= mask
        #print(bin(d1))

        if c1 < (size):
            p1 += 1
            c1 += 1
            continue

        d2 = 0
        p2 = p1+size
        while p2 < (bitlen):
            d2 <<= 1
            d2 |= getBit(data, p2)
            d2 &= mask
            #print(bin(d2))

            if c2 < (size):
                p2 += 1
                c2 += 1
                continue

            if d1 == d2 and d1 > 0:
                s1 = p1 - size
                s2 = p2 - size
                print("s1: %d\t  p1: %d\t  " % (s1, p1))
                print("s2: %d\t  p2: %d\t  " % (s2, p2))
                # complete the pattern until the numbers differ or meet
                while True:
                    p1 += 1
                    p2 += 1
                    #print("s1: %d\t  p1: %d\t  " % (s1, p1))
                    #print("s2: %d\t  p2: %d\t  " % (s2, p2))
                    if p2 >= bitlen:
                        break

                    b1 = getBit(data,p1)
                    b2 = getBit(data,p2)

                    if p1 == s2 or b1 != b2:
                        break

                length = p1 - s1
                c2 = 0
                p2 -= size

                bitSection, ent = bitSectString(data, s1, s1+length)
                if ent > minEntropy:
                    print("success:")
                    print("  * bit idx1: %4d (%4d bits) - '%s' %s" % (s1, length, bin(d1), hexlify(bitSection)))
                    print("  * bit idx2: %4d (%4d bits) - '%s'" % (s2, length, bin(d2)))
                    patterns.append((s1, s2, length, d1))
            #else:
            #    print("  * idx1: %d - '%s'  * idx2: %d - '%s'" % (p1, d1, p2, d2))
            p2 += 1
        p1 += 1

    return patterns


def bitSectString(string, startbit, endbit):
    '''
    bitsects a string... ie. chops out the bits from the middle of the string
    returns the new string and the entropy (ratio of 0:1)
    '''
    ones = 0
    zeros = 0
    entropy = [zeros, ones]

    s = b''
    bit = startbit

    Bidx = bit // 8
    bidx = (bit % 8)

    while bit < endbit:

        byte1 = string[Bidx]
        try:
            byte2 = string[Bidx+1]
        except IndexError:
            byte2 = 0

        byte = (byte1 << bidx) & 0xff
        byte |= (byte2 >> (8-bidx))
        #calculate entropy over the byte
        for bi in range(8):
            b = (byte>>bi) & 1
            entropy[b] += 1

        bit += 8
        Bidx += 1

        if bit > endbit:
            diff = bit-endbit
            mask = ~ ( (1<<diff) - 1 )
            byte &= mask

        s += correctbytes(byte)
    
    ent = (min(entropy)+1.0) / (max(entropy)+1)
    #print("entropy: %f" % ent)
    return (s, ent)


        
def genBitArray(string, startbit, endbit):
    '''
    bitsects a string... ie. chops out the bits from the middle of the string
    returns the new string and the entropy (ratio of 0:1)
    '''
    binStr, ent = bitSectString(string, startbit, endbit)

    s = []
    for byte in binStr:
        byte = byte
        for bitx in range(7, -1, -1):
            bit = (byte>>bitx) & 1
            s.append(bit)

    return (s, ent)


chars_top = [
        b" ", #000
        b" ", #001
        b"^", #010
        b"/", #011
        b" ", #100
        b" ", #101
        b"\\",#110
        b"-", #111
        ]

chars_mid = [
        b" ", #000
        b"|", #001
        b"#", #010
        b" ", #011
        b"|", #100
        b"#", #101
        b" ", #110
        b" ", #110
        ]

chars_bot = [
        b"-", #000
        b"/", #001
        b" ", #010
        b" ", #011
        b"\\",#100
        b"V", #101
        b" ", #110
        b" ", #110
        ]


def reprBitArray(bitAry, width=194):
    top = []
    mid = []
    bot = []

    arylen = len(bitAry)
    # top line
    #FIXME: UGGGGLY and kinda broken.
    fraction = 1.0 * arylen/width
    expand = [bitAry[int(x*fraction)] for x in range(width)]

    for bindex in range(width):
        bits = 0
        if bindex>0:
            bits += (expand[bindex-1]) << (2)
        bits += (expand[bindex]) << 1
        if bindex < width-1:
            bits += (expand[bindex+1])

        top.append( chars_top[ bits ] )
        mid.append( chars_mid[ bits ] )
        bot.append( chars_bot[ bits ] )

    tops = b"".join(top)
    mids = b"".join(mid)
    bots = b"".join(bot)
    return b"\n".join([tops, mids, bots])

def invertBits(data):
    output = []
    ldata = len(data)
    off = 0

    if ldata&1:
        output.append( correctbytes( ord( data[0:1] ) ^ 0xff) )
        off = 1

    if ldata&2:
        output.append( struct.pack( "<H", struct.unpack( "<H", data[off:off+2] )[0] ^ 0xffff) )
        off += 2

    #method 1
    #for idx in xrange( off, ldata, 4):
    #    output.append( struct.pack( "<I", struct.unpack( "<I", data[idx:idx+4] )[0] & 0xffff) )

    #method2
    count = ldata // 4
    #print(ldata, count)
    numlist = struct.unpack(b"<%dI" % count, data[off:] )
    modlist = [ struct.pack(b"<L", (x^0xffffffff) ) for x in numlist ]
    output.extend(modlist)

    return b''.join(output)


def diff_manchester_decode(data, align=False):
    # FIXME: not validated.  must find reference to validate against
    '''
    differential manchester encoding/decoding uses 2 symbols per data bit.
    there must always be a transition between the first and second symbol of a bit.
    bit values are determined by the existence/lack of transition between symbol pairs

    set align=True to allow *one* sync of the bits to clock.  ie, either the whole 
    thing lines up with a transition in the middle of every bit, or shift one, and
    try again.  one way *must* have transitions, or failure occurs
    '''
    syncd = False

    out = []
    last = 0
    obyte = 0
    for bidx in range(len(data)):
        byte = ord(data[bidx:bidx+1])
        for y in range(6, -1, -2):
            if not syncd:
                diff = last & 1
                bit0 = (byte >> (y+1)) & 1
                bit1 = (byte >> y) & 1
            else:
                diff = last >> 1
                bit0 = last & 1
                bit1 = (byte >> (y+1)) & 1

            if bit0 == bit1:
                if syncd or not align:
                    raise Exception("Differential Manchester Decoder cannot work with this data.  Sync fault at index %d,%d" % (bidx, y))

                syncd = 1
                # redo the last stuff with new info
                diff = last >> 1
                bit0 = last & 1
                bit1 = (byte >> (y+1)) & 1

            obyte <<= 1
            if diff != bit0:
                obyte |= 1

            last = (bit0 << 1) | bit1
        if (bidx & 1): 
            out.append(correctbytes(obyte))
            obyte = 0

    if not (bidx & 1):
        obyte << 4 # pad 0's on end
        out.append(correctbytes(obyte))
    return ''.join(out)



def biphase_mark_coding_encode(data):
    # FIXME: broken?  this looks more like BMC (biphase mark encoding)
    # FIXME: write encoder as well
    out = []
    last = 0
    for bidx in range(len(data)):
        byte = ord(data[bidx:bidx+1])
        obyte = 0
        for y in range(7, -1, -1):
            bit = (byte >> y) & 1
            obyte <<= 1
            if bit == last:
                obyte |= 1

            last = bit
        if bidx & 1:
            print("%d - write" % bidx)
            out.append(correctbytes(obyte))
        else:
            print("%d - skip" % bidx)
    if not (bidx & 1):
        print("%d - write" % bidx)
        out.append(correctbytes(obyte))

    return ''.join(out)

def manchester_decode(data, hilo=1):
    out = []
    last = 0
    obyte = 0
    for bidx in range(len(data)):
        byte = ord(data[bidx:bidx+1])
        for y in range(7, -1, -1):
            bit = (byte >> y) & 1

            if not (y & 1):   # every other bit counts
                obyte <<= 1
                if bit and not last:
                    if not hilo:
                        obyte |= 1
                elif last and not bit:
                    if hilo:
                        obyte |= 1

            last = bit
        if (bidx & 1): 
            out.append(correctbytes(obyte))
            obyte = 0

    if not (bidx & 1):
        obyte << 4 # pad 0's on end
        out.append(correctbytes(obyte))
    return ''.join(out)

def manchester_encode(data, hilo=1):
    '''
    for the sake of testing.
    assumings msb, and 
    '''
    if hilo:
        bits = (0b01, 0b10)
    else:
        bits = (0b10, 0b01)

    out = []
    for bidx in range(len(data)):
        byte = ord(data[bidx:bidx+1])
        obyte = 0
        for bitx in range(7,-1,-1):
            bit = (byte>>bitx) & 1
            obyte <<= 2
            obyte |= bits[bit]

        out.append(struct.pack(">H", obyte))
    return ''.join(out)

def findManchesterData(data, hilo=1):
    poss = []

    for x in range(8):
        try:
            newdata = shiftString(data, x)
            thing = manchester_decode(x, newdata)
            poss.append(thing)
        except:
            pass

def findManchester(data, minbytes=10):
    print("DEBUG: DATA=" + repr(data))
    success = []

    last = 0
    last2 = 0
    lastCount = 0
    minbits = minbytes * 8

    for bidx in range(len(data)):
        byt = ord(data[bidx:bidx+1])
        for btidx in range(0, 8, 2):
            # compare every other bits
            bit = (byt>>(8-btidx)) & 1

            if (bit + last + last2) in (1,2):
                lastCount += 1
            else:
                # we're done, or not started
                if lastCount >= minbits:
                    lenbytes = lastCount // 8
                    lenbits = lastCount % 8
                    startbyte = bidx - lenbytes
                    if lenbits > btidx:
                        startbyte += 1
                        lenbits -= 8
                    startbit = btidx - lenbits

                    stopbyte = startbyte + lenbytes + (0,1)[lenbits>0]
                    bytez = data[startbyte:stopbyte]

                    success.append((bidx, startbyte, startbit, bytez))
                lastCount = 0
            # cycle through
            last2 = last
            last = bit
    return success

