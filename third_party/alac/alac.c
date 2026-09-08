/*
 * ALAC (Apple Lossless Audio Codec) decoder
 * Copyright (c) 2005 David Hammerton
 * All rights reserved.
 *
 * This is the actual decoder.
 *
 * http://crazney.net/programs/itunes/alac.html
 * 
 * Permission is hereby granted, free of charge, to any person
 * obtaining a copy of this software and associated documentation
 * files (the "Software"), to deal in the Software without
 * restriction, including without limitation the rights to use,
 * copy, modify, merge, publish, distribute, sublicense, and/or
 * sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be
 * included in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
 * EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
 * OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
 * NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
 * HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
 * WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
 * OTHER DEALINGS IN THE SOFTWARE.
 *
 */


#include <stdint.h>
#include <stddef.h>
static void *ln_alac_copy(void *to,const void *from,size_t count)
{uint8_t *d=to;const uint8_t *s=from;for(size_t i=0;i<count;i++)d[i]=s[i];return to;}
static void *ln_alac_fill(void *to,int value,size_t count)
{uint8_t *d=to;for(size_t i=0;i<count;i++)d[i]=(uint8_t)value;return to;}
#define memcpy ln_alac_copy
#define memset ln_alac_fill
#define IBSS_ATTR
#define ICODE_ATTR
#include "decomp.h"

#define SIGNEXTEND24(val) (((signed)val<<8)>>8)

static int16_t predictor_coef_table[32] IBSS_ATTR;
static int16_t predictor_coef_table_a[32] IBSS_ATTR;
static int16_t predictor_coef_table_b[32] IBSS_ATTR;


/* stream reading */

/* Linnet: every bit access is bounded by the exact packet length. */
static inline uint32_t readbits_16(alac_file *alac,int bits)
{
    if(bits<0||bits>32||alac->failed){alac->failed=1;return 0;}
    uint32_t available=(uint32_t)(alac->input_end-alac->input_buffer)*8u-(uint32_t)alac->input_buffer_bitaccumulator;
    if((uint32_t)bits>available){alac->failed=1;return 0;}
    uint32_t value=0;
    while(bits--){value=(value<<1)|((*alac->input_buffer>>(7-alac->input_buffer_bitaccumulator))&1u);
        if(++alac->input_buffer_bitaccumulator==8){alac->input_buffer++;alac->input_buffer_bitaccumulator=0;}}
    return value;
}
static inline uint32_t readbits(alac_file *alac,int bits){return readbits_16(alac,bits);}
static inline int readbit(alac_file *alac){return (int)readbits_16(alac,1);}
static inline void unreadbits(alac_file *alac,int bits)
{
    uint32_t position=(uint32_t)(alac->input_buffer-alac->input_start)*8u+(uint32_t)alac->input_buffer_bitaccumulator;
    if(bits<0||(uint32_t)bits>position){alac->failed=1;return;}
    position-=(uint32_t)bits;alac->input_buffer=alac->input_start+position/8u;alac->input_buffer_bitaccumulator=(int)(position%8u);
}
static inline int ln_alac_clz(uint32_t value){int count=0;if(!value)return 32;while(!(value&0x80000000u)){count++;value<<=1;}return count;}
#define count_leading_zeros(x) ln_alac_clz((uint32_t)(x))

#define RICE_THRESHOLD 8 // maximum number of bits for a rice prefix.

static inline int32_t entropy_decode_value(alac_file* alac,
                             int readsamplesize,
                             int k) ICODE_ATTR_ALAC;
static inline int32_t entropy_decode_value(alac_file* alac,
                             int readsamplesize,
                             int k)
{
    if(k<0||k>31||readsamplesize<1||readsamplesize>32){alac->failed=1;return 0;}
    int32_t x = 0; // decoded value
    
    // read x, number of 1s before 0 represent the rice value.
    while (x <= RICE_THRESHOLD && readbit(alac))
    {
        x++;
    }
    
    if (x > RICE_THRESHOLD)
    {
        // read the number from the bit stream (raw value)
        int32_t value;
        
        value = readbits(alac, readsamplesize);
        
        /* mask value to readsamplesize size */
        if (readsamplesize != 32)
            value &= (((uint32_t)0xffffffff) >> (32 - readsamplesize));
        
        x = value;
    }
    else
    {
        if (k != 1)
        {
            int extrabits = readbits(alac, k);
            
            // x = x * (2^k - 1)
            x = (x << k) - x;
            
            if (extrabits > 1)
                x += extrabits - 1;
            else
                unreadbits(alac, 1);
        }
    }
    
    return x;
}

static void entropy_rice_decode(alac_file* alac,
                         int32_t* output_buffer,
                         int output_size,
                         int readsamplesize,
                         int rice_initialhistory,
                         int rice_kmodifier,
                         int rice_historymult,
                         int rice_kmodifier_mask) ICODE_ATTR_ALAC;
static void entropy_rice_decode(alac_file* alac,
                         int32_t* output_buffer,
                         int output_size,
                         int readsamplesize,
                         int rice_initialhistory,
                         int rice_kmodifier,
                         int rice_historymult,
                         int rice_kmodifier_mask)
{
    int                output_count;
    int                history = rice_initialhistory;
    int                sign_modifier = 0;
    
    for (output_count = 0; output_count < output_size; output_count++)
    {
        int32_t        decoded_value;
        int32_t        final_value;
        int32_t        k;
        
        k = 31 - rice_kmodifier - count_leading_zeros((history >> 9) + 3);
        
        if (k < 0) k += rice_kmodifier;
        else k = rice_kmodifier;
        
        decoded_value = entropy_decode_value(alac, readsamplesize, k);
        
        if(alac->failed)return;
        decoded_value += sign_modifier;
        final_value = (decoded_value + 1) / 2; // inc by 1 and shift out sign bit
        if (decoded_value & 1) // the sign is stored in the low bit
            final_value *= -1;
        
        output_buffer[output_count] = final_value;
        
        sign_modifier = 0;
        
        // update history
        history += (decoded_value * rice_historymult)
                - ((history * rice_historymult) >> 9);
        
        if (decoded_value > 0xFFFF)
            history = 0xFFFF;
        
        // special case, for compressed blocks of 0
        if ((history < 128) && (output_count + 1 < output_size))
        {
            int32_t        block_size;
            
            sign_modifier = 1;
            
            k = count_leading_zeros(history) + ((history + 16) / 64) - 24;
            
            // note: block_size is always 16bit
            block_size = entropy_decode_value(alac, 16, k) & rice_kmodifier_mask;
            
            if(alac->failed||block_size>output_size-output_count-1){alac->failed=1;return;}
            // got block_size 0s
            if (block_size > 0)
            {
                memset(&output_buffer[output_count + 1], 0, 
                       block_size * sizeof(*output_buffer));
                output_count += block_size;
            }
            
            if (block_size > 0xFFFF)
                sign_modifier = 0;
            
            history = 0;
        }
    }
}

#define SIGN_EXTENDED32(val, bits) ((val << (32 - bits)) >> (32 - bits))

#define SIGN_ONLY(v) \
                     ((v < 0) ? (-1) : \
                                ((v > 0) ? (1) : \
                                           (0)))

static void predictor_decompress_fir_adapt(int32_t *error_buffer,
                                           int32_t *buffer_out,
                                           int output_size,
                                           int readsamplesize,
                                           int16_t *predictor_coef_table,
                                           int predictor_coef_num,
                                           int predictor_quantitization) ICODE_ATTR_ALAC;
static void predictor_decompress_fir_adapt(int32_t *error_buffer,
                                           int32_t *buffer_out,
                                           int output_size,
                                           int readsamplesize,
                                           int16_t *predictor_coef_table,
                                           int predictor_coef_num,
                                           int predictor_quantitization)
{
    int i;

    /* first sample always copies */
    *buffer_out = *error_buffer;

    if (!predictor_coef_num)
    {
        if (output_size <= 1) return;
        memcpy(buffer_out+1, error_buffer+1, (output_size-1) * 4);
        return;
    }

    if (predictor_coef_num == 0x1f) /* 11111 - max value of predictor_coef_num */
    { /* second-best case scenario for fir decompression,
       * error describes a small difference from the previous sample only
       */
        if (output_size <= 1) return;
        for (i = 0; i < output_size - 1; i++)
        {
            int32_t prev_value;
            int32_t error_value;

            prev_value = buffer_out[i];
            error_value = error_buffer[i+1];
            buffer_out[i+1] = SIGN_EXTENDED32((prev_value + error_value), readsamplesize);
        }
        return;
    }

    /* read warm-up samples */
    if (predictor_coef_num > 0)
    {
        int i;
        for (i = 0; i < predictor_coef_num; i++)
        {
            int32_t val;

            val = buffer_out[i] + error_buffer[i+1];

            val = SIGN_EXTENDED32(val, readsamplesize);

            buffer_out[i+1] = val;
        }
    }

    /* 4 and 8 are very common cases (the only ones i've seen).

      The following code is an initial attempt to unroll and optimise
      these two cases by the Rockbox project.  More work is needed. 
     */

    /* optimised case: 4 */
    if (predictor_coef_num == 4)
    {
        /* Linnet: retain the five-sample window and four adaptive coefficients
         * locally. Explicit signed16 stores preserve upstream coefficient wrap;
         * each adaptation still stops as soon as its residual crosses zero. */
        int16_t c0=predictor_coef_table[0],c1=predictor_coef_table[1];
        int16_t c2=predictor_coef_table[2],c3=predictor_coef_table[3];
        int32_t x0=buffer_out[0],x1=buffer_out[1],x2=buffer_out[2];
        int32_t x3=buffer_out[3],x4=buffer_out[4];
        for (i = 4 + 1; i < output_size; i++)
        {
            int sum = 0;
            int outval;
            int error_val = error_buffer[i];

            sum = (x4-x0)*c0+(x3-x0)*c1+(x2-x0)*c2+(x1-x0)*c3;

            outval = (1 << (predictor_quantitization-1)) + sum;
            outval = outval >> predictor_quantitization;
            outval = outval + x0 + error_val;
            outval = SIGN_EXTENDED32(outval, readsamplesize);

            buffer_out[4+1] = outval;

            if (error_val > 0)
            {
#define ADAPT_POS(c,x,n) do { if(error_val>0){int val=x0-(x);if(val){ \
                if(val<0){(c)=(int16_t)((c)+1);val=-val;}else (c)=(int16_t)((c)-1); \
                error_val-=(val>>predictor_quantitization)*(n);}} } while(0)
                ADAPT_POS(c3,x1,1);ADAPT_POS(c2,x2,2);
                ADAPT_POS(c1,x3,3);ADAPT_POS(c0,x4,4);
#undef ADAPT_POS
            }
            else if (error_val < 0)
            {
#define ADAPT_NEG(c,x,n) do { if(error_val<0){int val=x0-(x);if(val){ \
                if(val>0){(c)=(int16_t)((c)+1);val=-val;}else (c)=(int16_t)((c)-1); \
                error_val-=(val>>predictor_quantitization)*(n);}} } while(0)
                ADAPT_NEG(c3,x1,1);ADAPT_NEG(c2,x2,2);
                ADAPT_NEG(c1,x3,3);ADAPT_NEG(c0,x4,4);
#undef ADAPT_NEG
            }

            x0=x1;x1=x2;x2=x3;x3=x4;x4=outval;buffer_out++;
        }
        predictor_coef_table[0]=c0;predictor_coef_table[1]=c1;
        predictor_coef_table[2]=c2;predictor_coef_table[3]=c3;
        return;
    }

    /* optimised case: 8 */
    if (predictor_coef_num == 8)
    {
        for (i = 8 + 1;
             i < output_size;
             i++)
        {
            int sum;
            int outval;
            int error_val = error_buffer[i];

            sum = (buffer_out[8] - buffer_out[0]) * predictor_coef_table[0]
                + (buffer_out[7] - buffer_out[0]) * predictor_coef_table[1]
                + (buffer_out[6] - buffer_out[0]) * predictor_coef_table[2]
                + (buffer_out[5] - buffer_out[0]) * predictor_coef_table[3]
                + (buffer_out[4] - buffer_out[0]) * predictor_coef_table[4]
                + (buffer_out[3] - buffer_out[0]) * predictor_coef_table[5]
                + (buffer_out[2] - buffer_out[0]) * predictor_coef_table[6]
                + (buffer_out[1] - buffer_out[0]) * predictor_coef_table[7];

            outval = (1 << (predictor_quantitization-1)) + sum;
            outval = outval >> predictor_quantitization;
            outval = outval + buffer_out[0] + error_val;
            outval = SIGN_EXTENDED32(outval, readsamplesize);

            buffer_out[8+1] = outval;

            if (error_val > 0)
            {
                int predictor_num = 8 - 1;

                while (predictor_num >= 0 && error_val > 0)
                {
                    int val = buffer_out[0] - buffer_out[8 - predictor_num];

                    if (val!=0) {
                       if (val < 0) {
                         predictor_coef_table[predictor_num]++;
                         val=-val;
                       } else {
                         predictor_coef_table[predictor_num]--;
                       }
                       error_val -= ((val >> predictor_quantitization) * (8 - predictor_num));
                    }                      
                    predictor_num--;
                }
            }
            else if (error_val < 0)
            {
                int predictor_num = 8 - 1;

                while (predictor_num >= 0 && error_val < 0)
                {
                    int val = buffer_out[0] - buffer_out[8 - predictor_num];
                    if (val != 0) {
                      if (val > 0) {
                        predictor_coef_table[predictor_num]++;
                        val=-val; /* neg value */
                      } else {
                        predictor_coef_table[predictor_num]--;
                      }
                      error_val -= ((val >> predictor_quantitization) * (8 - predictor_num));
                    }
                    predictor_num--;
                }
            }

            buffer_out++;
        }
        return;
    } 

    /* general case */
    if (predictor_coef_num > 0)
    {
        for (i = predictor_coef_num + 1;
             i < output_size;
             i++)
        {
            int j;
            int sum = 0;
            int outval;
            int error_val = error_buffer[i];

            for (j = 0; j < predictor_coef_num; j++)
            {
                sum += (buffer_out[predictor_coef_num-j] - buffer_out[0]) *
                       predictor_coef_table[j];
            }

            outval = (1 << (predictor_quantitization-1)) + sum;
            outval = outval >> predictor_quantitization;
            outval = outval + buffer_out[0] + error_val;
            outval = SIGN_EXTENDED32(outval, readsamplesize);

            buffer_out[predictor_coef_num+1] = outval;

            if (error_val > 0)
            {
                int predictor_num = predictor_coef_num - 1;

                while (predictor_num >= 0 && error_val > 0)
                {
                    int val = buffer_out[0] - buffer_out[predictor_coef_num - predictor_num];
                    int sign = SIGN_ONLY(val);

                    predictor_coef_table[predictor_num] -= sign;

                    val *= sign; /* absolute value */

                    error_val -= ((val >> predictor_quantitization) *
                                  (predictor_coef_num - predictor_num));

                    predictor_num--;
                }
            }
            else if (error_val < 0)
            {
                int predictor_num = predictor_coef_num - 1;

                while (predictor_num >= 0 && error_val < 0)
                {
                    int val = buffer_out[0] - buffer_out[predictor_coef_num - predictor_num];
                    int sign = - SIGN_ONLY(val);

                    predictor_coef_table[predictor_num] -= sign;

                    val *= sign; /* neg value */

                    error_val -= ((val >> predictor_quantitization) *
                                  (predictor_coef_num - predictor_num));

                    predictor_num--;
                }
            }

            buffer_out++;
        }
    }
}

static void deinterlace_16(int32_t* buffer0,
                           int32_t* buffer1,
                           int numsamples,
                           uint8_t interlacing_shift,
                           uint8_t interlacing_leftweight) ICODE_ATTR_ALAC;
static void deinterlace_16(int32_t* buffer0,
                           int32_t* buffer1,
                           int numsamples,
                           uint8_t interlacing_shift,
                           uint8_t interlacing_leftweight)
{
    int i;
    if (numsamples <= 0) return;

    /* weighted interlacing */
    if (interlacing_leftweight)
    {
        for (i = 0; i < numsamples; i++)
        {
            int32_t difference, midright;

            midright = buffer0[i];
            difference = buffer1[i];

            buffer0[i] = ((midright - ((difference * interlacing_leftweight)
                            >> interlacing_shift)) + difference) << SCALE16;
            buffer1[i] = (midright - ((difference * interlacing_leftweight) 
                            >> interlacing_shift)) << SCALE16;
        }

        return;
    }

    /* otherwise basic interlacing took place */
    for (i = 0; i < numsamples; i++)
    {
        buffer0[i] = buffer0[i] << SCALE16;
        buffer1[i] = buffer1[i] << SCALE16;
    }
}

static void deinterlace_24(int32_t *buffer0, int32_t *buffer1,
                           int uncompressed_bytes,
                           int32_t *uncompressed_bytes_buffer0,
                           int32_t *uncompressed_bytes_buffer1,
                           int numsamples,
                           uint8_t interlacing_shift,
                           uint8_t interlacing_leftweight) ICODE_ATTR_ALAC;
static void deinterlace_24(int32_t *buffer0, int32_t *buffer1,
                           int uncompressed_bytes,
                           int32_t *uncompressed_bytes_buffer0,
                           int32_t *uncompressed_bytes_buffer1,
                           int numsamples,
                           uint8_t interlacing_shift,
                           uint8_t interlacing_leftweight)
{
    int i;
    if (numsamples <= 0) return;
    
    /* weighted interlacing */
    if (interlacing_leftweight)
    {
        for (i = 0; i < numsamples; i++)
        {
            int32_t difference, midright;
            
            midright = buffer0[i];
            difference = buffer1[i];
            
            buffer0[i] = ((midright - ((difference * interlacing_leftweight)
                            >> interlacing_shift)) + difference) << SCALE24;
            buffer1[i] = (midright - ((difference * interlacing_leftweight) 
                            >> interlacing_shift)) << SCALE24;
            
            if (uncompressed_bytes)
            {
                uint32_t mask = ~(0xFFFFFFFF << (uncompressed_bytes * 8));
                buffer0[i] <<= (uncompressed_bytes * 8);
                buffer1[i] <<= (uncompressed_bytes * 8);
                
                buffer0[i] |= uncompressed_bytes_buffer0[i] & mask;
                buffer1[i] |= uncompressed_bytes_buffer1[i] & mask;
            }

        }
        
        return;
    }
    
    /* otherwise basic interlacing took place */
    for (i = 0; i < numsamples; i++)
    {
        if (uncompressed_bytes)
        {
            uint32_t mask = ~(0xFFFFFFFF << (uncompressed_bytes * 8));
            buffer0[i] <<= (uncompressed_bytes * 8);
            buffer1[i] <<= (uncompressed_bytes * 8);
            
            buffer0[i] |= uncompressed_bytes_buffer0[i] & mask;
            buffer1[i] |= uncompressed_bytes_buffer1[i] & mask;
        }
        
        buffer0[i] = buffer0[i] << SCALE24;
        buffer1[i] = buffer1[i] << SCALE24;
    }
    
}

static inline int decode_frame_mono(
                    alac_file *alac,
                    int32_t outputbuffer[ALAC_MAX_CHANNELS][ALAC_BLOCKSIZE],
                    void (*yield)(void))
{
    int hassize;
    int isnotcompressed;
    int readsamplesize;
    int infosamplesize = alac->setinfo_sample_size;
    int outputsamples = alac->setinfo_max_samples_per_frame;

    int uncompressed_bytes;
    int ricemodifier;


    /* 2^result = something to do with output waiting.
     * perhaps matters if we read > 1 frame in a pass?
     */
    readbits(alac, 4);

    readbits(alac, 12); /* unknown, skip 12 bits */

    hassize = readbits(alac, 1); /* the output sample size is stored soon */

    /* number of bytes in the (compressed) stream that are not compressed */
    uncompressed_bytes = readbits(alac, 2);

    isnotcompressed = readbits(alac, 1); /* whether the frame is compressed */

    if (hassize)
    {
        /* now read the number of samples,
         * as a 32bit integer */
        outputsamples = readbits(alac, 32);
    }

    if(alac->failed||outputsamples<=0||outputsamples>ALAC_BLOCKSIZE||(uint32_t)outputsamples>alac->setinfo_max_samples_per_frame||uncompressed_bytes)return -1;
    readsamplesize = infosamplesize - (uncompressed_bytes * 8);

    if (!isnotcompressed)
    { /* so it is compressed */
        int predictor_coef_num;
        int prediction_type;
        int prediction_quantitization;
        int i;

        /* skip 16 bits, not sure what they are. seem to be used in
         * two channel case */
        readbits(alac, 8);
        readbits(alac, 8);

        prediction_type = readbits(alac, 4);
        prediction_quantitization = readbits(alac, 4);

        ricemodifier = readbits(alac, 3);
        predictor_coef_num = readbits(alac, 5);

        if(prediction_type||!prediction_quantitization||(predictor_coef_num!=31&&predictor_coef_num>=outputsamples))return -1;
        /* read the predictor table */
        for (i = 0; i < predictor_coef_num; i++)
        {
            predictor_coef_table[i] = (int16_t)readbits(alac, 16);
        }

        if (uncompressed_bytes)
        {
            int i;
            for (i = 0; i < outputsamples; i++)
            {
                outputbuffer[0][i] = readbits(alac, uncompressed_bytes * 8);
                outputbuffer[1][i] = outputbuffer[0][i];
            }
        }

        yield();

        entropy_rice_decode(alac,
                            outputbuffer[0],
                            outputsamples,
                            readsamplesize,
                            alac->setinfo_rice_initialhistory,
                            alac->setinfo_rice_kmodifier,
                            ricemodifier * alac->setinfo_rice_historymult / 4,
                            (1 << alac->setinfo_rice_kmodifier) - 1);

        yield();

        if (prediction_type == 0)
        { /* adaptive fir */
            predictor_decompress_fir_adapt(outputbuffer[0],
                                           outputbuffer[0],
                                           outputsamples,
                                           readsamplesize,
                                           predictor_coef_table,
                                           predictor_coef_num,
                                           prediction_quantitization);
        }
        else
        {
            //fprintf(stderr, "FIXME: unhandled predicition type: %i\n", prediction_type);
            /* i think the only other prediction type (or perhaps this is just a
             * boolean?) runs adaptive fir twice.. like:
             * predictor_decompress_fir_adapt(predictor_error, tempout, ...)
             * predictor_decompress_fir_adapt(predictor_error, outputsamples ...)
             * little strange..
             */
        }

    }
    else
    { /* not compressed, easy case */
        if (infosamplesize <= 16)
        {
            int i;
            for (i = 0; i < outputsamples; i++)
            {
                int32_t audiobits = readbits(alac, infosamplesize);

                audiobits = SIGN_EXTENDED32(audiobits, infosamplesize);

                outputbuffer[0][i] = audiobits;
            }
        }
        else
        {
            int i;
            for (i = 0; i < outputsamples; i++)
            {
                int32_t audiobits;

                audiobits = readbits(alac, 16);
                /* special case of sign extension..
                 * as we'll be ORing the low 16bits into this */
                audiobits = audiobits << (infosamplesize - 16);
                audiobits |= readbits(alac, infosamplesize - 16);
                audiobits = SIGNEXTEND24(audiobits);

                outputbuffer[0][i] = audiobits;
            }
        }
        uncompressed_bytes = 0; // always 0 for uncompressed
    }

    yield();

    switch(infosamplesize)
    {
    case 16:
    {
        int i;
        for (i = 0; i < outputsamples; i++)
        {
            /* Output mono data as stereo */
            outputbuffer[0][i] = outputbuffer[0][i] << SCALE16;
            outputbuffer[1][i] = outputbuffer[0][i];
        }
        break;
    }
    case 24:
    {
        int i;
        for (i = 0; i < outputsamples; i++)
        {
            int32_t sample = outputbuffer[0][i];
            
            if (uncompressed_bytes)
            {
                uint32_t mask;
                sample = sample << (uncompressed_bytes * 8);
                mask = ~(0xFFFFFFFF << (uncompressed_bytes * 8));
                sample |= outputbuffer[0][i] & mask;
            }
            
            outputbuffer[0][i] = sample << SCALE24;
            outputbuffer[1][i] = outputbuffer[0][i];
        }
        break;
    }
    case 20:
    case 32:
        //fprintf(stderr, "FIXME: unimplemented sample size %i\n", infosamplesize);
        break;
    default:
        break;
    }

    return alac->failed?-1:outputsamples;
}

static inline int decode_frame_stereo(
                    alac_file *alac,
                    int32_t outputbuffer[ALAC_MAX_CHANNELS][ALAC_BLOCKSIZE],
                    void (*yield)(void))
{
    int hassize;
    int isnotcompressed;
    int readsamplesize;
    int infosamplesize = alac->setinfo_sample_size;
    int outputsamples = alac->setinfo_max_samples_per_frame;
    int uncompressed_bytes;

    uint8_t interlacing_shift;
    uint8_t interlacing_leftweight;

    /* 2^result = something to do with output waiting.
     * perhaps matters if we read > 1 frame in a pass?
     */
    readbits(alac, 4);

    readbits(alac, 12); /* unknown, skip 12 bits */

    hassize = readbits(alac, 1); /* the output sample size is stored soon */

    /* the number of bytes in the (compressed) stream that are not compressed */
    uncompressed_bytes = readbits(alac, 2);

    isnotcompressed = readbits(alac, 1); /* whether the frame is compressed */

    if (hassize)
    {
        /* now read the number of samples,
         * as a 32bit integer */
        outputsamples = readbits(alac, 32);
    }

    if(alac->failed||outputsamples<=0||outputsamples>ALAC_BLOCKSIZE||(uint32_t)outputsamples>alac->setinfo_max_samples_per_frame||uncompressed_bytes)return -1;
    readsamplesize = infosamplesize - (uncompressed_bytes * 8) + 1;

    yield();
    if (!isnotcompressed)
    { /* compressed */
        int predictor_coef_num_a;
        int prediction_type_a;
        int prediction_quantitization_a;
        int ricemodifier_a;

        int predictor_coef_num_b;
        int prediction_type_b;
        int prediction_quantitization_b;
        int ricemodifier_b;

        int i;

        interlacing_shift = readbits(alac, 8);
        interlacing_leftweight = readbits(alac, 8);

        /******** channel 1 ***********/
        prediction_type_a = readbits(alac, 4);
        prediction_quantitization_a = readbits(alac, 4);

        ricemodifier_a = readbits(alac, 3);
        predictor_coef_num_a = readbits(alac, 5);

        if(interlacing_shift>31||prediction_type_a||!prediction_quantitization_a||(predictor_coef_num_a!=31&&predictor_coef_num_a>=outputsamples))return -1;
        /* read the predictor table */
        for (i = 0; i < predictor_coef_num_a; i++)
        {
            predictor_coef_table_a[i] = (int16_t)readbits(alac, 16);
        }

        /******** channel 2 *********/
        prediction_type_b = readbits(alac, 4);
        prediction_quantitization_b = readbits(alac, 4);

        ricemodifier_b = readbits(alac, 3);
        predictor_coef_num_b = readbits(alac, 5);

        if(prediction_type_b||!prediction_quantitization_b||(predictor_coef_num_b!=31&&predictor_coef_num_b>=outputsamples))return -1;
        /* read the predictor table */
        for (i = 0; i < predictor_coef_num_b; i++)
        {
            predictor_coef_table_b[i] = (int16_t)readbits(alac, 16);
        }

        /*********************/
        if (uncompressed_bytes)
        { /* see mono case */
            int i;
            for (i = 0; i < outputsamples; i++)
            {
                outputbuffer[0][i] = readbits(alac, uncompressed_bytes * 8);
                outputbuffer[1][i] = readbits(alac, uncompressed_bytes * 8);
            }
        }

        yield();
        /* channel 1 */
        entropy_rice_decode(alac,
                            outputbuffer[0],
                            outputsamples,
                            readsamplesize,
                            alac->setinfo_rice_initialhistory,
                            alac->setinfo_rice_kmodifier,
                            ricemodifier_a * alac->setinfo_rice_historymult / 4,
                            (1 << alac->setinfo_rice_kmodifier) - 1);

        yield();
        if (prediction_type_a == 0)
        { /* adaptive fir */
            predictor_decompress_fir_adapt(outputbuffer[0],
                                           outputbuffer[0],
                                           outputsamples,
                                           readsamplesize,
                                           predictor_coef_table_a,
                                           predictor_coef_num_a,
                                           prediction_quantitization_a);
        }
        else
        { /* see mono case */
            //fprintf(stderr, "FIXME: unhandled predicition type: %i\n", prediction_type_a);
        }

        yield();

        /* channel 2 */
        entropy_rice_decode(alac,
                            outputbuffer[1],
                            outputsamples,
                            readsamplesize,
                            alac->setinfo_rice_initialhistory,
                            alac->setinfo_rice_kmodifier,
                            ricemodifier_b * alac->setinfo_rice_historymult / 4,
                            (1 << alac->setinfo_rice_kmodifier) - 1);

        yield();
        if (prediction_type_b == 0)
        { /* adaptive fir */
            predictor_decompress_fir_adapt(outputbuffer[1],
                                           outputbuffer[1],
                                           outputsamples,
                                           readsamplesize,
                                           predictor_coef_table_b,
                                           predictor_coef_num_b,
                                           prediction_quantitization_b);
        }
        else
        {
            //fprintf(stderr, "FIXME: unhandled predicition type: %i\n", prediction_type_b);
        }
    }
    else
    { /* not compressed, easy case */
        if (infosamplesize <= 16)
        {
            int i;
            for (i = 0; i < outputsamples; i++)
            {
                int32_t audiobits_a, audiobits_b;

                audiobits_a = readbits(alac, infosamplesize);
                audiobits_b = readbits(alac, infosamplesize);

                audiobits_a = SIGN_EXTENDED32(audiobits_a, infosamplesize);
                audiobits_b = SIGN_EXTENDED32(audiobits_b, infosamplesize);

                outputbuffer[0][i] = audiobits_a;
                outputbuffer[1][i] = audiobits_b;
            }
        }
        else
        {
            int i;
            for (i = 0; i < outputsamples; i++)
            {
                int32_t audiobits_a, audiobits_b;

                audiobits_a = readbits(alac, 16);
                audiobits_a = audiobits_a << (infosamplesize - 16);
                audiobits_a |= readbits(alac, infosamplesize - 16);
                audiobits_a = SIGNEXTEND24(audiobits_a);

                audiobits_b = readbits(alac, 16);
                audiobits_b = audiobits_b << (infosamplesize - 16);
                audiobits_b |= readbits(alac, infosamplesize - 16);
                audiobits_b = SIGNEXTEND24(audiobits_b);

                outputbuffer[0][i] = audiobits_a;
                outputbuffer[1][i] = audiobits_b;
            }
        }
        uncompressed_bytes = 0; // always 0 for uncompressed
        interlacing_shift = 0;
        interlacing_leftweight = 0;
    }

    yield();

    switch(infosamplesize)
    {
    case 16:
    {
        deinterlace_16(outputbuffer[0],
                       outputbuffer[1],
                       outputsamples,
                       interlacing_shift,
                       interlacing_leftweight);
        break;
    }
    case 24:
    {
        deinterlace_24(outputbuffer[0],
                       outputbuffer[1],
                       uncompressed_bytes,
                       outputbuffer[0],
                       outputbuffer[1],
                       outputsamples,
                       interlacing_shift,
                       interlacing_leftweight);            
        break;
    }
    case 20:
    case 32:
        //fprintf(stderr, "FIXME: unimplemented sample size %i\n", infosamplesize);
        break;
    default:
        break;
    }
    return alac->failed?-1:outputsamples;
}

int alac_decode_frame(alac_file *alac,
                      unsigned char *inbuffer, uint32_t input_bytes,
                      int32_t outputbuffer[ALAC_MAX_CHANNELS][ALAC_BLOCKSIZE],
                      void (*yield)(void))
{
    int channels;
    int outputsamples;
    unsigned char *input_buffer_start;

    /* setup the stream */
    if(!alac||!inbuffer||!yield||!input_bytes||input_bytes>32768u||alac->setinfo_sample_size!=16||!alac->setinfo_max_samples_per_frame||alac->setinfo_max_samples_per_frame>4096||alac->setinfo_rice_kmodifier>14)return -1;
    alac->input_start=inbuffer;alac->input_end=inbuffer+input_bytes;alac->failed=0;
    alac->input_buffer = inbuffer;
    alac->input_buffer_bitaccumulator = 0;
    
    /* save to gather byte consumption */
    input_buffer_start = alac->input_buffer;

    channels = readbits(alac, 3);

    if(channels+1!=alac->setinfo_7f)return -1;
    /* TODO: The mono and stereo functions should be combined. */
    switch(channels)
    {
        case 0: /* 1 channel */
            outputsamples=decode_frame_mono(alac,outputbuffer,yield);
            break;
        case 1: /* 2 channels */
            outputsamples=decode_frame_stereo(alac,outputbuffer,yield);
            break;
        default: /* Unsupported */
            return -1;
    }
    
    if(outputsamples<=0||alac->failed||readbits(alac,3)!=7)return -1;
    while(alac->input_buffer_bitaccumulator)if(readbit(alac))return -1;
    if(alac->failed||alac->input_buffer!=alac->input_end)return -1;
    /* Exact packet consumption, including END element and zero byte padding. */
    alac->bytes_consumed = (int)(alac->input_buffer - input_buffer_start);

    return alac->failed?-1:outputsamples;
}

/* rockbox: not used
void create_alac(int samplesize, int numchannels, alac_file* alac)
{
    alac->samplesize = samplesize;
    alac->numchannels = numchannels;
    alac->bytespersample = (samplesize / 8) * numchannels;
} */
