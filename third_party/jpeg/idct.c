/***************************************************************************
*             __________               __   ___.
*   Open      \______   \ ____   ____ |  | _\_ |__   _______  ___
*   Source     |       _//  _ \_/ ___\|  |/ /| __ \ /  _ \  \/  /
*   Jukebox    |    |   (  <_> )  \___|    < | \_\ (  <_> > <  <
*   Firmware   |____|_  /\____/ \___  >__|_ \|___  /\____/__/\_ \
*                     \/            \/     \/    \/            \/
*
* JPEG image viewer
* (This is a real mess if it has to be coded in one single C file)
*
* File scrolling addition (C) 2005 Alexander Spyridakis
* Copyright (C) 2004 Jörg Hohensohn aka [IDC]Dragon
* Heavily borrowed from the IJG implementation (C) Thomas G. Lane
* Small & fast downscaling IDCT (C) 2002 by Guido Vollbeding  JPEGclub.org
*
* This program is free software; you can redistribute it and/or
* modify it under the terms of the GNU General Public License
* as published by the Free Software Foundation; either version 2
* of the License, or (at your option) any later version.
*
* This software is distributed on an "AS IS" basis, WITHOUT WARRANTY OF ANY
* KIND, either express or implied.
*
****************************************************************************/

#include <stdint.h>
/* Linnet: bounded baseline coefficients, signed64 intermediates and workspace.
 * Use multiplication for signed scaling; no overflowing signed shifts or
 * upstream short truncation. All intermediate magnitudes are below2^48 for
 * |DC|<=2048, |AC|<=1023 and quantization<=255. */
static unsigned range_limit(int64_t value){value+=128;return value<0?0:value>255?255:(unsigned)value;}
#define MULTIPLY16(v,c) ((int64_t)(v)*(int64_t)(c))
#define DEQUANTIZE MULTIPLY16
#define DESCALE(x,n) (((x)+(INT64_C(1)<<((n)-1)))>>(n))
#define CONST_BITS 13
#define PASS1_BITS 2


/* Some C compilers fail to reduce "FIX(constant)" at compile time, thus
* causing a lot of useless floating-point operations at run time.
* To get around this we use the following pre-calculated constants.
* If you change CONST_BITS you may want to add appropriate values.
* (With a reasonable C compiler, you can just rely on the FIX() macro...)
*/
#define FIX_0_298631336  2446 /* FIX(0.298631336) */
#define FIX_0_390180644  3196 /* FIX(0.390180644) */
#define FIX_0_541196100  4433 /* FIX(0.541196100) */
#define FIX_0_765366865  6270 /* FIX(0.765366865) */
#define FIX_0_899976223  7373 /* FIX(0.899976223) */
#define FIX_1_175875602  9633 /* FIX(1.175875602) */
#define FIX_1_501321110 12299 /* FIX(1.501321110) */
#define FIX_1_847759065 15137 /* FIX(1.847759065) */
#define FIX_1_961570560 16069 /* FIX(1.961570560) */
#define FIX_2_053119869 16819 /* FIX(2.053119869) */
#define FIX_2_562915447 20995 /* FIX(2.562915447) */
#define FIX_3_072711026 25172 /* FIX(3.072711026) */



void ln_jpeg_idct8(unsigned char* p_byte, int* inptr, int* quantptr, int skip_line)
{
    int64_t tmp0, tmp1, tmp2, tmp3;
    int64_t tmp10, tmp11, tmp12, tmp13;
    int64_t z1, z2, z3, z4, z5;
    int64_t * wsptr;
    unsigned char* outptr;
    int ctr;
    int64_t workspace[64];  /* buffers data between passes */

    /* Pass 1: process columns from input, store into work array. */
    /* Note results are scaled up by sqrt(8) compared to a true IDCT; */
    /* furthermore, we scale the results by 2**PASS1_BITS. */

    wsptr = workspace;
    for (ctr = 8; ctr > 0; ctr--)
    {
    /* Due to quantization, we will usually find that many of the input
    * coefficients are zero, especially the AC terms.  We can exploit this
    * by short-circuiting the IDCT calculation for any column in which all
    * the AC terms are zero.  In that case each output is equal to the
    * DC coefficient (with scale factor as needed).
    * With typical images and quantization tables, half or more of the
    * column DCT calculations can be simplified this way.
    */

        if ((inptr[8*1] | inptr[8*2] | inptr[8*3]
           | inptr[8*4] | inptr[8*5] | inptr[8*6] | inptr[8*7]) == 0)
        {
            /* AC terms all zero */
            int64_t dcval = DEQUANTIZE(inptr[8*0], quantptr[8*0]) * (1 << PASS1_BITS);

            wsptr[8*0] = wsptr[8*1] = wsptr[8*2] = wsptr[8*3] = wsptr[8*4]
                       = wsptr[8*5] = wsptr[8*6] = wsptr[8*7] = dcval;
            inptr++;      /* advance pointers to next column */
            quantptr++;
            wsptr++;
            continue;
        }

        /* Even part: reverse the even part of the forward DCT. */
        /* The rotator is sqrt(2)*c(-6). */

        z2 = DEQUANTIZE(inptr[8*2], quantptr[8*2]);
        z3 = DEQUANTIZE(inptr[8*6], quantptr[8*6]);

        z1 = MULTIPLY16(z2 + z3, FIX_0_541196100);
        tmp2 = z1 + MULTIPLY16(z3, - FIX_1_847759065);
        tmp3 = z1 + MULTIPLY16(z2, FIX_0_765366865);

        z2 = DEQUANTIZE(inptr[8*0], quantptr[8*0]);
        z3 = DEQUANTIZE(inptr[8*4], quantptr[8*4]);

        tmp0 = (z2 + z3) * (1 << CONST_BITS);
        tmp1 = (z2 - z3) * (1 << CONST_BITS);

        tmp10 = tmp0 + tmp3;
        tmp13 = tmp0 - tmp3;
        tmp11 = tmp1 + tmp2;
        tmp12 = tmp1 - tmp2;

        /* Odd part per figure 8; the matrix is unitary and hence its
           transpose is its inverse.  i0..i3 are y7,y5,y3,y1 respectively. */

        tmp0 = DEQUANTIZE(inptr[8*7], quantptr[8*7]);
        tmp1 = DEQUANTIZE(inptr[8*5], quantptr[8*5]);
        tmp2 = DEQUANTIZE(inptr[8*3], quantptr[8*3]);
        tmp3 = DEQUANTIZE(inptr[8*1], quantptr[8*1]);

        z1 = tmp0 + tmp3;
        z2 = tmp1 + tmp2;
        z3 = tmp0 + tmp2;
        z4 = tmp1 + tmp3;
        z5 = MULTIPLY16(z3 + z4, FIX_1_175875602); /* sqrt(2) * c3 */

        tmp0 = MULTIPLY16(tmp0, FIX_0_298631336); /* sqrt(2) * (-c1+c3+c5-c7) */
        tmp1 = MULTIPLY16(tmp1, FIX_2_053119869); /* sqrt(2) * ( c1+c3-c5+c7) */
        tmp2 = MULTIPLY16(tmp2, FIX_3_072711026); /* sqrt(2) * ( c1+c3+c5-c7) */
        tmp3 = MULTIPLY16(tmp3, FIX_1_501321110); /* sqrt(2) * ( c1+c3-c5-c7) */
        z1 = MULTIPLY16(z1, - FIX_0_899976223); /* sqrt(2) * (c7-c3) */
        z2 = MULTIPLY16(z2, - FIX_2_562915447); /* sqrt(2) * (-c1-c3) */
        z3 = MULTIPLY16(z3, - FIX_1_961570560); /* sqrt(2) * (-c3-c5) */
        z4 = MULTIPLY16(z4, - FIX_0_390180644); /* sqrt(2) * (c5-c3) */

        z3 += z5;
        z4 += z5;

        tmp0 += z1 + z3;
        tmp1 += z2 + z4;
        tmp2 += z2 + z3;
        tmp3 += z1 + z4;

        /* Final output stage: inputs are tmp10..tmp13, tmp0..tmp3 */

        wsptr[8*0] = (int) DESCALE(tmp10 + tmp3, CONST_BITS-PASS1_BITS);
        wsptr[8*7] = (int) DESCALE(tmp10 - tmp3, CONST_BITS-PASS1_BITS);
        wsptr[8*1] = (int) DESCALE(tmp11 + tmp2, CONST_BITS-PASS1_BITS);
        wsptr[8*6] = (int) DESCALE(tmp11 - tmp2, CONST_BITS-PASS1_BITS);
        wsptr[8*2] = (int) DESCALE(tmp12 + tmp1, CONST_BITS-PASS1_BITS);
        wsptr[8*5] = (int) DESCALE(tmp12 - tmp1, CONST_BITS-PASS1_BITS);
        wsptr[8*3] = (int) DESCALE(tmp13 + tmp0, CONST_BITS-PASS1_BITS);
        wsptr[8*4] = (int) DESCALE(tmp13 - tmp0, CONST_BITS-PASS1_BITS);

        inptr++; /* advance pointers to next column */
        quantptr++;
        wsptr++;
    }

    /* Pass 2: process rows from work array, store into output array. */
    /* Note that we must descale the results by a factor of 8 == 2**3, */
    /* and also undo the PASS1_BITS scaling. */

    wsptr = workspace;
    for (ctr = 0; ctr < 8; ctr++)
    {
        outptr = p_byte + (ctr*skip_line);
        /* Rows of zeroes can be exploited in the same way as we did with columns.
        * However, the column calculation has created many nonzero AC terms, so
        * the simplification applies less often (typically 5% to 10% of the time).
        * On machines with very fast multiplication, it's possible that the
        * test takes more time than it's worth.  In that case this section
        * may be commented out.
        */

#ifndef NO_ZERO_ROW_TEST
        if ((wsptr[1] | wsptr[2] | wsptr[3]
           | wsptr[4] | wsptr[5] | wsptr[6] | wsptr[7]) == 0)
        {
            /* AC terms all zero */
            unsigned char dcval = range_limit((int) DESCALE((int64_t) wsptr[0],
                PASS1_BITS+3));

            outptr[0] = dcval;
            outptr[1] = dcval;
            outptr[2] = dcval;
            outptr[3] = dcval;
            outptr[4] = dcval;
            outptr[5] = dcval;
            outptr[6] = dcval;
            outptr[7] = dcval;

            wsptr += 8; /* advance pointer to next row */
            continue;
        }
#endif

        /* Even part: reverse the even part of the forward DCT. */
        /* The rotator is sqrt(2)*c(-6). */

        z2 = (int64_t) wsptr[2];
        z3 = (int64_t) wsptr[6];

        z1 = MULTIPLY16(z2 + z3, FIX_0_541196100);
        tmp2 = z1 + MULTIPLY16(z3, - FIX_1_847759065);
        tmp3 = z1 + MULTIPLY16(z2, FIX_0_765366865);

        tmp0 = ((int64_t) wsptr[0] + (int64_t) wsptr[4]) * (1 << CONST_BITS);
        tmp1 = ((int64_t) wsptr[0] - (int64_t) wsptr[4]) * (1 << CONST_BITS);

        tmp10 = tmp0 + tmp3;
        tmp13 = tmp0 - tmp3;
        tmp11 = tmp1 + tmp2;
        tmp12 = tmp1 - tmp2;

        /* Odd part per figure 8; the matrix is unitary and hence its
        * transpose is its inverse. i0..i3 are y7,y5,y3,y1 respectively. */

        tmp0 = (int64_t) wsptr[7];
        tmp1 = (int64_t) wsptr[5];
        tmp2 = (int64_t) wsptr[3];
        tmp3 = (int64_t) wsptr[1];

        z1 = tmp0 + tmp3;
        z2 = tmp1 + tmp2;
        z3 = tmp0 + tmp2;
        z4 = tmp1 + tmp3;
        z5 = MULTIPLY16(z3 + z4, FIX_1_175875602); /* sqrt(2) * c3 */

        tmp0 = MULTIPLY16(tmp0, FIX_0_298631336); /* sqrt(2) * (-c1+c3+c5-c7) */
        tmp1 = MULTIPLY16(tmp1, FIX_2_053119869); /* sqrt(2) * ( c1+c3-c5+c7) */
        tmp2 = MULTIPLY16(tmp2, FIX_3_072711026); /* sqrt(2) * ( c1+c3+c5-c7) */
        tmp3 = MULTIPLY16(tmp3, FIX_1_501321110); /* sqrt(2) * ( c1+c3-c5-c7) */
        z1 = MULTIPLY16(z1, - FIX_0_899976223); /* sqrt(2) * (c7-c3) */
        z2 = MULTIPLY16(z2, - FIX_2_562915447); /* sqrt(2) * (-c1-c3) */
        z3 = MULTIPLY16(z3, - FIX_1_961570560); /* sqrt(2) * (-c3-c5) */
        z4 = MULTIPLY16(z4, - FIX_0_390180644); /* sqrt(2) * (c5-c3) */

        z3 += z5;
        z4 += z5;

        tmp0 += z1 + z3;
        tmp1 += z2 + z4;
        tmp2 += z2 + z3;
        tmp3 += z1 + z4;

        /* Final output stage: inputs are tmp10..tmp13, tmp0..tmp3 */

        outptr[0] = range_limit((int) DESCALE(tmp10 + tmp3,
            CONST_BITS+PASS1_BITS+3));
        outptr[7] = range_limit((int) DESCALE(tmp10 - tmp3,
            CONST_BITS+PASS1_BITS+3));
        outptr[1] = range_limit((int) DESCALE(tmp11 + tmp2,
            CONST_BITS+PASS1_BITS+3));
        outptr[6] = range_limit((int) DESCALE(tmp11 - tmp2,
            CONST_BITS+PASS1_BITS+3));
        outptr[2] = range_limit((int) DESCALE(tmp12 + tmp1,
            CONST_BITS+PASS1_BITS+3));
        outptr[5] = range_limit((int) DESCALE(tmp12 - tmp1,
            CONST_BITS+PASS1_BITS+3));
        outptr[3] = range_limit((int) DESCALE(tmp13 + tmp0,
            CONST_BITS+PASS1_BITS+3));
        outptr[4] = range_limit((int) DESCALE(tmp13 - tmp0,
            CONST_BITS+PASS1_BITS+3));

        wsptr += 8; /* advance pointer to next row */
    }
}



