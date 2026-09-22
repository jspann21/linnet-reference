#include "hal/s5l8702/board.h"
#include "hal/s5l8702/ata_pio.h"
#include "hal/s5l8702/registers.h"
#define ATA(offset) LN_REG(0x38700000u+(offset))
extern uint32_t ln_time_us(void);
static uint16_t identify[256] __attribute__((aligned(32)));
static uint32_t phase,deadline,expires,words,error;
void ln_storage_probe(unsigned operation,uint32_t lba,uint32_t result[16]) {
    uint32_t now=ln_time_us();uint16_t status=0;
    if(operation==2) {
        phase=0;words=error=0;
        if(!ln_s5l_board_disk_power()){error=1;goto done;}
        ATA(0x18)=1;deadline=now+10000u;expires=now+15000000u;phase=1;
    } else if(operation==4) {
        if(phase!=8 || error || lba>0x0fffffffu){error=8;goto done;}
        words=0;
        if(!ln_s5l_ata_write(0x6c,0xe0|((lba>>24)&15)) || !ln_s5l_ata_write(0x5c,1) ||
           !ln_s5l_ata_write(0x60,lba&255) || !ln_s5l_ata_write(0x64,(lba>>8)&255) ||
           !ln_s5l_ata_write(0x68,(lba>>16)&255) || !ln_s5l_ata_write(0x70,0x20)){error=9;goto done;}
        phase=7;deadline=now;expires=now+2000000u;
    } else if(phase && phase<8 && !error) {
        if((int32_t)(now-expires)>=0){error=2;goto done;}
        if((int32_t)(now-deadline)<0)goto done;
        switch(phase) {
        case 1:ATA(0x18)=0;deadline=now+10000u;phase=2;break;
        case 2:ATA(12)=1;deadline=now+10000u;phase=3;break;
        case 3:ATA(12)=0;deadline=now+100000u;phase=4;break;
        case 4:ATA(0)=1;deadline=now+200000u;phase=5;break;
        case 5:
            ATA(0x2c)=0x191f7;ATA(0x68)=0;ATA(0x18)=0x40;phase=6;break;
        case 6:
            if(!ln_s5l_ata_read(0x74,&status)){error=3;break;}
            if(status==0xff || (status&0x80))break;
            if(!ln_s5l_ata_write(0x6c,0) || !ln_s5l_ata_write(0x70,0xec)){error=4;break;}
            phase=7;break;
        case 7:
            if(!ln_s5l_ata_read(0x74,&status)){error=5;break;}
            if(status&0x80)break;
            if(status&1){error=6;break;}
            if(!(status&8))break;
            for(unsigned count=0;count<32 && words<256;count++) {
                if(!ln_s5l_ata_read(0x54,identify+words)){error=7;break;}
                ++words;
            }
            if(words==256)phase=8;
            break;
        }
    }
done:
    result[3]=phase;result[4]=error;result[5]=words;result[6]=status;
    result[7]=(uint32_t)(uintptr_t)identify;
    result[8]=phase?ATA(0x78):0;result[9]=deadline;result[10]=expires;
}
