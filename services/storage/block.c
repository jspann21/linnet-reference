#include "services/storage/block.h"
#include "hal/api/platform.h"
enum slot_state { FREE,QUEUED,ACTIVE,DONE };
struct slot {
    enum slot_state state;enum ln_block_op op;
    uint64_t lba;
    uint32_t sectors,generation,deadline,id,status,transferred,read_ahead;
    uint8_t *caller;
    bool canceled,direct;
    uint8_t data[4096] __attribute__((aligned(32)));
};
static struct slot slots[8];
static uint8_t transfer[4096] __attribute__((aligned(32)));
static uint8_t cache[2][4096] __attribute__((aligned(32)));
static uint64_t cache_lba[2];
static uint64_t window_first,window_count;
static uint32_t cache_sectors[2],cache_next,next_id,active_count,active_sectors,active_deadline;
static void invalidate_cache(void){cache_sectors[0]=cache_sectors[1]=cache_next=0;}
static uint32_t active_slots[8],active_offsets[8],streak;
static bool active_retry,recovering,frozen;
static bool barrier_failed;
static uint32_t quiesce_state,quiesce_deadline;
static bool idle_allowed,idle_retry_active;
static uint32_t power_task,last_activity,standby_at,idle_retry_at;
static struct ln_block_info metrics;
#if !defined(LINNET_PROFILE_RELEASE)
static uint32_t injected,active_fault;
static struct block_performance {
    uint32_t calls,service,gaps,gap_us,max_gap,last_end,last_id;
    bool tracking,saturated;
} perf;
static struct block_schedule_performance {
    uint32_t done_at[8],taken,ready_us,ready_max,flags;
} schedule_perf;
static void perf_add(uint32_t *value,uint32_t amount){
    if(amount>=UINT32_MAX-*value){*value=UINT32_MAX;perf.saturated=true;}
    else *value+=amount;
}
static uint32_t perf_read_id(void){
    return active_count&&!recovering&&slots[active_slots[0]].op==LN_BLOCK_READ?
        slots[active_slots[0]].id:0u;
}
static void schedule_perf_add(uint32_t *value,uint32_t amount){
    if(amount>=UINT32_MAX-*value){*value=UINT32_MAX;schedule_perf.flags|=0x80000000u;}
    else *value+=amount;
}
#endif
static void copy(uint8_t *to,const uint8_t *from,uint32_t bytes) {
#if defined(__arm__)
    extern void ln_memory_copy(void *,const void *,uint32_t);ln_memory_copy(to,from,bytes);
#else
    for(uint32_t i=0;i<bytes;++i)to[i]=from[i];
#endif
}
static void complete(struct slot *s,uint32_t status,uint32_t sectors) {
    bool issued=s->state==ACTIVE;
    s->status=s->canceled?LN_ATA_CANCELED:status;s->transferred=sectors;s->state=DONE;
#if !defined(LINNET_PROFILE_RELEASE)
    schedule_perf.done_at[(uint32_t)(s-slots)]=ln_time_us();
#endif
    ++metrics.completed;if(s->status==LN_ATA_CANCELED)++metrics.canceled;
    else if(s->status!=LN_ATA_OK)++metrics.failed;
    if(issued&&status!=LN_ATA_OK&&(s->op==LN_BLOCK_WRITE||s->op==LN_BLOCK_FLUSH||s->op==LN_BLOCK_STANDBY))barrier_failed=true;
}
static int oldest(enum slot_state state) {
    int found=-1;
    for(uint32_t i=0;i<8u;++i)if(slots[i].state==state&&
        (found<0||(int32_t)(slots[i].id-slots[(uint32_t)found].id)<0))found=(int)i;
    return found;
}
void ln_block_init(uint32_t now) {
    for(uint32_t i=0;i<8u;++i)slots[i].state=FREE;
    metrics=(struct ln_block_info){0};invalidate_cache();next_id=active_count=streak=quiesce_state=0;
    frozen=recovering=active_retry=false;
    barrier_failed=false;window_first=window_count=0;
    idle_allowed=idle_retry_active=false;power_task=standby_at=idle_retry_at=0;last_activity=now;
#if !defined(LINNET_PROFILE_RELEASE)
    injected=active_fault=0;perf=(struct block_performance){0};
    schedule_perf=(struct block_schedule_performance){0};
#endif
    ln_ata_init(now);
}
static bool submit(enum ln_block_op op,uint64_t lba,uint32_t sectors,void *bytes,
    uint32_t generation,uint32_t limit,uint32_t read_ahead,bool direct,uint32_t *id) {
    uint32_t now=ln_time_us();
    if(!id||frozen||metrics.quarantined||op<LN_BLOCK_READ||op>LN_BLOCK_WAKE||
        (int32_t)(limit-now)<=0||limit-now>30000000u)return false;
    bool data=op==LN_BLOCK_READ||op==LN_BLOCK_WRITE;
    if(data&&(!bytes||!sectors||sectors>(direct?192u:8u)||lba>UINT64_MAX-sectors))return false;
    if(direct&&op!=LN_BLOCK_READ)return false;
    if(!data&&(bytes||sectors||lba))return false;
    struct ln_ata_state device;ln_ata_state_snapshot(&device);
    if((!device.initialized&&device.powered&&!device.initializing)||device.failed||!device.sectors||
        (data&&(lba>=device.sectors||sectors>device.sectors-lba))||
        (data&&window_count&&(lba<window_first||lba-window_first>=window_count||sectors>window_count-(lba-window_first)))||
        (op==LN_BLOCK_WRITE&&(!device.can_flush||barrier_failed)))return false;
    for(uint32_t i=0;i<8u;++i)if(slots[i].state==FREE){
        struct slot *s=&slots[i];
        if(++next_id==0)++next_id;
        s->op=op;s->lba=lba;s->sectors=sectors;s->generation=generation;s->deadline=limit;
        s->read_ahead=read_ahead;
        s->id=next_id;s->caller=bytes;s->canceled=false;s->direct=direct;s->transferred=0;
        if(op==LN_BLOCK_WRITE)copy(s->data,bytes,sectors*512u);
        s->state=QUEUED;*id=s->id;++metrics.submitted;return true;
    }
    return false;
}
bool ln_block_submit(enum ln_block_op op,uint64_t lba,uint32_t sectors,void *bytes,
    uint32_t generation,uint32_t limit,uint32_t *id){
    return submit(op,lba,sectors,bytes,generation,limit,8u,false,id);
}
bool ln_block_submit_read(uint64_t lba,uint32_t sectors,void *bytes,uint32_t generation,
    uint32_t limit,uint32_t read_ahead,uint32_t *id){
    if(read_ahead!=1u&&read_ahead!=8u)return false;
    return submit(LN_BLOCK_READ,lba,sectors,bytes,generation,limit,read_ahead,false,id);
}
bool ln_block_submit_direct_read(uint64_t lba,uint32_t sectors,void *bytes,
    uint32_t generation,uint32_t limit,uint32_t *id){
    return submit(LN_BLOCK_READ,lba,sectors,bytes,generation,limit,sectors,true,id);
}
static void active_complete(uint32_t status,uint32_t transferred) {
    last_activity=ln_time_us();standby_at=0;
    struct slot *first=&slots[active_slots[0]];
    if(status==LN_ATA_OK&&first->op==LN_BLOCK_READ&&!first->direct){
        uint32_t way=cache_next;cache_next^=1u;
        cache_lba[way]=first->lba;cache_sectors[way]=active_sectors;
        copy(cache[way],transfer,active_sectors*512u);
    }
    for(uint32_t i=0;i<active_count;++i){
        struct slot *s=&slots[active_slots[i]];uint32_t offset=active_offsets[i];
        uint32_t count=transferred>offset?transferred-offset:0;
        if(count>s->sectors)count=s->sectors;
        if(status==LN_ATA_OK&&!s->canceled&&s->op==LN_BLOCK_READ&&!s->direct)
            copy(s->caller,transfer+offset*512u,s->sectors*512u);
        complete(s,status,count);
    }
    if(status==LN_ATA_OK)streak=0;
    else if(status!=LN_ATA_CANCELED&&++streak>=3u)metrics.quarantined=1;
    if(status!=LN_ATA_OK)invalidate_cache();
    active_count=0;active_retry=recovering=false;
}
static bool issue(void) {
#if !defined(LINNET_PROFILE_RELEASE)
    /* A retry is a new issued attempt even when its caller request id repeats. */
    perf.tracking=false;
#endif
    struct slot *s=&slots[active_slots[0]];
    bool data=s->op==LN_BLOCK_READ||s->op==LN_BLOCK_WRITE;
    return ln_ata_start((enum ln_ata_op)s->op,s->lba,data?active_sectors:0,
        data?(s->direct?s->caller:transfer):0,active_deadline);
}
static void step_inner(uint32_t now) {
    if(idle_retry_active&&(int32_t)(now-idle_retry_at)>=0)idle_retry_active=false;
    ln_ata_step(now);
    struct ln_ata_state device;ln_ata_state_snapshot(&device);
    /* Expire queued requests even during a slow disk reset. */
    for(uint32_t i=0;i<8u;++i)if(slots[i].state==QUEUED&&
        (int32_t)(now-slots[i].deadline)>=0)complete(&slots[i],LN_ATA_TIMEOUT,0);
    if(power_task){
        if(power_task==2u){
            if(device.initializing)return;
            power_task=0;last_activity=now;
            if(device.failed){++metrics.idle_failures;idle_retry_at=now+5000000u;idle_retry_active=true;}
            return;
        }
        struct ln_ata_result power_result;
        if(!ln_ata_take(&power_result))return;
        uint32_t finished_task=power_task;power_task=0;
        if(power_result.status!=LN_ATA_OK){
            ++metrics.idle_failures;idle_retry_at=now+5000000u;idle_retry_active=true;invalidate_cache();
            if(finished_task==1u)barrier_failed=true;
            ln_ata_recover(now);power_task=2u;
        }else if(finished_task==1u)standby_at=now;
        else {last_activity=now;standby_at=0;}
        return;
    }
    if(active_count){
        if(recovering){
            if(device.failed||(int32_t)(now-active_deadline)>=0){active_complete(LN_ATA_TIMEOUT,0);return;}
            if(device.initialized){recovering=false;if(!issue())active_complete(LN_ATA_IO,0);}
            return;
        }
        struct ln_ata_result result;
        if(!ln_ata_take(&result))return;
        bool forced=false;
#if !defined(LINNET_PROFILE_RELEASE)
        forced=active_fault!=0;
        if(active_fault==2u){result.status=LN_ATA_IO;result.sectors_done=0;}
        if(active_fault==4u){result.status=LN_ATA_CANCELED;result.sectors_done=0;}
        active_fault=0;
#endif
        /* Only reads may be retried. A write error has uncertain persistence
         * and must propagate to the publication owner, never be hidden. */
        if(!forced&&result.status!=LN_ATA_OK&&result.status!=LN_ATA_CANCELED&&!active_retry&&
            slots[active_slots[0]].op==LN_BLOCK_READ&&
            (int32_t)(active_deadline-now)>100000){
            bool canceled=true;for(uint32_t i=0;i<active_count;++i)if(!slots[active_slots[i]].canceled)canceled=false;
            if(!canceled){active_retry=recovering=true;++metrics.retries;invalidate_cache();ln_ata_recover(now);return;}
        }
        active_complete(result.status,result.sectors_done);
        if(result.status!=LN_ATA_OK&&device.failed&&!metrics.quarantined)ln_ata_recover(now);
        return;
    }
    if(quiesce_state==2u){
        struct ln_ata_result result;
        if(ln_ata_take(&result))quiesce_state=result.status==LN_ATA_OK?3u:4u;
        else if((int32_t)(now-quiesce_deadline)>=0)quiesce_state=4u;
        if(quiesce_state==4u)barrier_failed=true;
        return;
    }
    int index=oldest(QUEUED);
    if(index<0){
        if(quiesce_state==1u){
            if(device.failed||metrics.quarantined||barrier_failed||(int32_t)(now-quiesce_deadline)>=0)quiesce_state=4u;
            else if(!device.powered)quiesce_state=3u;
            else if(device.initialized&&!device.busy){
#if !defined(LINNET_PROFILE_RELEASE)
                if(injected==5u){injected=0;barrier_failed=true;quiesce_state=4u;++metrics.failed;return;}
#endif
                /* A completed standby barrier remains valid until ATA data,
                 * wake, reset or failure clears power_safe. No new command is
                 * needed merely to acknowledge the same quiescent state. */
                if(device.power_safe)quiesce_state=3u;
                else if(ln_ata_start(LN_ATA_STANDBY,0,0,0,quiesce_deadline))quiesce_state=2u;
                else quiesce_state=4u;
            }
        }
        else if(!frozen&&idle_allowed&&!barrier_failed&&!device.failed&&!device.initializing&&!device.busy&&
                !metrics.quarantined&&!idle_retry_active){
            bool free=true;for(uint32_t i=0;i<8u;++i)if(slots[i].state!=FREE)free=false;
            if(free&&device.powered&&standby_at&&
               now-standby_at>=2000000u&&device.can_power_off){
                if(ln_ata_power_off())invalidate_cache();
                else {++metrics.idle_failures;idle_retry_at=now+5000000u;idle_retry_active=true;}
            }else if(free&&device.powered&&!device.sleeping&&!standby_at&&(device.standby_supported||device.can_power_off)&&
                     now-last_activity>=device.idle_timeout_us){
                if(ln_ata_start(LN_ATA_STANDBY,0,0,0,now+30000000u))power_task=1u;
                else {++metrics.idle_failures;idle_retry_at=now+5000000u;idle_retry_active=true;}
            }
        }
        return;
    }
    struct slot *s=&slots[(uint32_t)index];
    /* Admission predates earlier completion: a failed publication barrier
     * must also stop writes already queued, and later flush/standby cannot
     * turn uncertain persistence into a successful durability report. */
    if(barrier_failed&&(s->op==LN_BLOCK_WRITE||s->op==LN_BLOCK_FLUSH||s->op==LN_BLOCK_STANDBY)){
        complete(s,LN_ATA_QUARANTINED,0);return;
    }
    if(metrics.quarantined){complete(s,LN_ATA_QUARANTINED,0);return;}
    if(device.failed){complete(s,LN_ATA_OFFLINE,0);return;}
    if(device.initializing||device.busy)return;
    /* Two ways keep corresponding primary/mirror FAT sectors resident. Every
     * media write/reset/window change invalidates both, preserving readback. */
    if(s->op==LN_BLOCK_READ&&!s->direct)for(uint32_t way=0;way<2u;++way){
        if(cache_sectors[way]&&s->lba>=cache_lba[way]&&
           s->lba-cache_lba[way]+s->sectors<=cache_sectors[way]){
            copy(s->caller,cache[way]+(uint32_t)(s->lba-cache_lba[way])*512u,s->sectors*512u);
            cache_next=way^1u;++metrics.cache_hits;complete(s,LN_ATA_OK,s->sectors);return;
        }
    }
    if(!device.powered){
        invalidate_cache();
        if(ln_ata_power_on(now))power_task=2u;
        else {++metrics.idle_failures;complete(s,LN_ATA_IO,0);}
        return;
    }
    if(device.sleeping){
        if(ln_ata_start(LN_ATA_WAKE,0,0,0,s->deadline))power_task=3u;
        else complete(s,LN_ATA_IO,0);
        return;
    }
    if(!device.initialized)return;
    active_count=1;active_slots[0]=(uint32_t)index;active_offsets[0]=0;
    active_sectors=s->sectors;active_deadline=s->deadline;s->state=ACTIVE;
    active_retry=recovering=false;
    if(s->op==LN_BLOCK_WRITE){invalidate_cache();copy(transfer,s->data,s->sectors*512u);}
    if((s->op==LN_BLOCK_READ||s->op==LN_BLOCK_WRITE)&&!s->direct){
        uint32_t read_ahead=s->read_ahead;
        while(active_count<8u){
            int next=oldest(QUEUED);if(next<0)break;
            struct slot *candidate=&slots[(uint32_t)next];
            if(candidate->op!=s->op||candidate->generation!=s->generation||
                candidate->lba!=s->lba+active_sectors||candidate->sectors>8u-active_sectors)break;
            active_slots[active_count]=(uint32_t)next;active_offsets[active_count]=active_sectors;
            if(s->op==LN_BLOCK_WRITE)copy(transfer+active_sectors*512u,candidate->data,candidate->sectors*512u);
            active_sectors+=candidate->sectors;candidate->state=ACTIVE;++active_count;++metrics.coalesced;
            if(candidate->read_ahead<read_ahead)read_ahead=candidate->read_ahead;
            if((int32_t)(candidate->deadline-active_deadline)<0)active_deadline=candidate->deadline;
        }
        if(s->op==LN_BLOCK_READ&&active_sectors<read_ahead){
            uint64_t end=window_count?window_first+window_count:device.sectors;
            uint32_t ahead=end-s->lba<read_ahead?(uint32_t)(end-s->lba):read_ahead;
            metrics.read_ahead_sectors+=ahead-active_sectors;active_sectors=ahead;
        }
    }
#if !defined(LINNET_PROFILE_RELEASE)
    active_fault=injected;
    if(active_fault==5u&&s->op!=LN_BLOCK_FLUSH)active_fault=0;
    else injected=0;
    if(active_fault==1u||active_fault==3u||active_fault==5u){
        uint32_t fault=active_fault;active_fault=0;
        active_complete(fault==1u?LN_ATA_TIMEOUT:LN_ATA_IO,0);
        if(fault==3u)ln_ata_recover(now);
        return;
    }
#endif
    if(!issue())active_complete(LN_ATA_IO,0);
}
void ln_block_step(uint32_t now) {
    uint32_t started=ln_time_us();
#if !defined(LINNET_PROFILE_RELEASE)
    uint32_t read_id=perf_read_id();
    if(perf.tracking&&read_id&&read_id==perf.last_id){
        uint32_t gap=started-perf.last_end;perf_add(&perf.gaps,1u);perf_add(&perf.gap_us,gap);
        if(gap>perf.max_gap)perf.max_gap=gap;
    }
#endif
    step_inner(now);
    uint32_t ended=ln_time_us(),elapsed=ended-started;if(elapsed>metrics.max_service_us)metrics.max_service_us=elapsed;
#if !defined(LINNET_PROFILE_RELEASE)
    perf_add(&perf.calls,1u);perf_add(&perf.service,elapsed);
    perf.last_id=perf_read_id();perf.tracking=perf.last_id!=0u;perf.last_end=ended;
#endif
}
#if !defined(LINNET_PROFILE_RELEASE)
void ln_block_performance(uint32_t out[32]){
    /* Fill the shared output directly; avoid two nested64-byte snapshots. */
    ln_ata_performance(out+4);
    out[0]=0x504f4953u;out[1]=0u;out[2]=out[19];
    out[3]=out[18]|(recovering?4u:0u)|(perf.saturated?0x80000000u:0u);
    out[30]=out[16];out[31]=out[17];
    out[16]=perf.calls;out[17]=perf.service;out[18]=metrics.max_service_us;
    out[19]=perf.gaps;out[20]=perf.gap_us;out[21]=perf.max_gap;
    out[22]=metrics.cache_hits;out[23]=metrics.read_ahead_sectors;
    out[24]=metrics.submitted;out[25]=metrics.completed;out[26]=metrics.failed;
    out[27]=metrics.retries;out[28]=metrics.canceled;out[29]=0;
    for(uint32_t i=0;i<8u;i++)if(slots[i].state==QUEUED||slots[i].state==ACTIVE)++out[29];
}
#endif
bool ln_block_take(uint32_t generation,struct ln_block_completion *out) {
    if(!out)return false;
    for(uint32_t i=0;i<8u;++i){struct slot *s=&slots[i];
        if(s->state==DONE&&s->generation==generation){
#if !defined(LINNET_PROFILE_RELEASE)
            uint32_t ready=ln_time_us()-schedule_perf.done_at[i];
            schedule_perf_add(&schedule_perf.taken,1u);schedule_perf_add(&schedule_perf.ready_us,ready);
            if(ready>schedule_perf.ready_max)schedule_perf.ready_max=ready;
#endif
            *out=(struct ln_block_completion){s->id,s->generation,s->status,s->transferred};s->state=FREE;return true;
        }
    }
    return false;
}
void ln_block_cancel(uint32_t generation) {
    for(uint32_t i=0;i<8u;++i){struct slot *s=&slots[i];if(s->state==FREE||s->generation!=generation)continue;
        s->canceled=true;if(s->state==QUEUED)complete(s,LN_ATA_CANCELED,0);
        else if(s->state==DONE&&s->status!=LN_ATA_CANCELED){s->status=LN_ATA_CANCELED;++metrics.canceled;}
    }
}
void ln_block_snapshot(struct ln_block_info *out) {
    if(!out)return;struct ln_ata_state device;ln_ata_state_snapshot(&device);
    metrics.sectors=device.sectors;metrics.initializing=device.initializing;
    metrics.ready=(device.initialized||(!device.powered&&device.sectors))&&!device.failed&&!metrics.quarantined;
    metrics.power_transition=power_task;
    metrics.pending=0;for(uint32_t i=0;i<8u;++i)if(slots[i].state==QUEUED||slots[i].state==ACTIVE)++metrics.pending;
    *out=metrics;
}
uint32_t ln_block_next_deadline(uint32_t now) {
    uint32_t next=ln_ata_next_deadline(now);
    for(uint32_t i=0;i<8u;++i)if(slots[i].state==QUEUED&&
        (int32_t)(slots[i].deadline-next)<0)next=slots[i].deadline;
    struct ln_ata_state device;ln_ata_state_snapshot(&device);
    if(oldest(QUEUED)>=0&&!active_count&&!device.initializing&&!power_task)next=now;
    if(idle_allowed&&!frozen&&!power_task&&device.powered){
        uint32_t due=standby_at?standby_at+2000000u:last_activity+device.idle_timeout_us;
        if(idle_retry_active&&(int32_t)(idle_retry_at-due)>0)due=idle_retry_at;
        if((int32_t)(due-now)>0&&(int32_t)(due-next)<0)next=due;
    }
    return next;
}
enum block_schedule_state {BLOCK_SCHEDULE_IDLE=0,BLOCK_SCHEDULE_RUNNABLE=1,
    BLOCK_SCHEDULE_WAITING=2,BLOCK_SCHEDULE_COMPLETION=3};
static enum block_schedule_state block_schedule_state(uint32_t now,uint32_t *deadline_out){
    uint32_t next=ln_ata_next_deadline(now);bool queued=false,done=false,expired=false;
    for(uint32_t i=0;i<8u;++i){
        if(slots[i].state==QUEUED){queued=true;
            if((int32_t)(slots[i].deadline-next)<0)next=slots[i].deadline;
            if((int32_t)(now-slots[i].deadline)>=0)expired=true;
        }
        else if(slots[i].state==DONE)done=true;
    }
    if(recovering&&(int32_t)(active_deadline-next)<0)next=active_deadline;
    if((quiesce_state==1u||quiesce_state==2u)&&
       (int32_t)(quiesce_deadline-next)<0)next=quiesce_deadline;
    if(deadline_out)*deadline_out=next;
    if(done)return BLOCK_SCHEDULE_COMPLETION;
    struct ln_ata_state device;ln_ata_state_snapshot(&device);
    /* IDLE ATA with a block owner means the ATA result is ready to take. */
    if((active_count&&!recovering&&!device.busy)||
       (recovering&&(device.failed||device.initialized||(int32_t)(now-active_deadline)>=0))||
       (power_task&&!device.initializing&&!device.busy)||
       (quiesce_state==2u&&!device.busy)||
       (quiesce_state==1u&&!queued&&!active_count&&!device.initializing&&!device.busy&&
        (device.failed||metrics.quarantined||barrier_failed||!device.powered||device.initialized||
         (int32_t)(now-quiesce_deadline)>=0))||
       (queued&&!active_count&&!device.initializing&&!device.busy&&!power_task)||expired)
        return BLOCK_SCHEDULE_RUNNABLE;
    bool work=queued||active_count||recovering||power_task||device.initializing||device.busy||
        quiesce_state==1u||quiesce_state==2u;
    if(!work)return BLOCK_SCHEDULE_IDLE;
    return (int32_t)(next-now)<=0?BLOCK_SCHEDULE_RUNNABLE:BLOCK_SCHEDULE_WAITING;
}
bool ln_block_idle_wait(uint32_t now,uint32_t *deadline){
    return block_schedule_state(now,deadline)==BLOCK_SCHEDULE_WAITING;
}
#if !defined(LINNET_PROFILE_RELEASE)
enum ln_block_schedule ln_block_schedule_state(uint32_t now,uint32_t *deadline_out){
    return (enum ln_block_schedule)block_schedule_state(now,deadline_out);
}
void ln_block_schedule_metrics(uint32_t out[4]){
    out[0]=schedule_perf.taken;out[1]=schedule_perf.ready_us;
    out[2]=schedule_perf.ready_max;out[3]=schedule_perf.flags;
}
#endif
void ln_block_allow_idle(bool allowed){idle_allowed=allowed;}
uint32_t ln_block_request_timeout(void){
    struct ln_ata_state device;ln_ata_state_snapshot(&device);
    return (!device.powered||device.sleeping||device.initializing||power_task)?30000000u:5000000u;
}
int ln_block_quiesce(uint32_t now,uint32_t limit) {
    if(!quiesce_state){
        if((int32_t)(limit-now)<=0||limit-now>30000000u)return -1;
        frozen=true;quiesce_state=1;quiesce_deadline=limit;
    }
    if(quiesce_state<3u&&(int32_t)(now-quiesce_deadline)>=0)quiesce_state=4;
    return quiesce_state==3u?1:quiesce_state==4u?-1:0;
}
bool ln_block_resume(void) {
    if(!frozen&&!quiesce_state)return true;
    if(quiesce_state!=3u)return false;frozen=false;quiesce_state=0;return true;
}
bool ln_block_recover(uint32_t now) {
    for(uint32_t i=0;i<8u;++i)if(slots[i].state!=FREE)return false;
    if(active_count||quiesce_state==2u||power_task)return false;
    metrics.quarantined=0;streak=quiesce_state=0;invalidate_cache();frozen=barrier_failed=false;
    standby_at=0;last_activity=now;idle_retry_active=false;
    window_first=window_count=0;ln_ata_recover(now);return true;
}
bool ln_block_set_window(uint64_t first,uint64_t sectors) {
    struct ln_ata_state device;ln_ata_state_snapshot(&device);
    /* A powered-down idle device retains its verified geometry. The first
     * request owns bounded wake/re-identification; changing the admission
     * window does not require spinning up or powering on the medium. */
    if((!device.initialized&&(device.powered||!device.sectors))||device.failed||metrics.quarantined||
       !sectors||first>=device.sectors||sectors>device.sectors-first)return false;
    for(uint32_t i=0;i<8u;++i)if(slots[i].state!=FREE)return false;
    if(active_count||frozen)return false;
    window_first=first;window_count=sectors;invalidate_cache();return true;
}
#if !defined(LINNET_PROFILE_RELEASE)
bool ln_block_inject(uint32_t fault) { if(!fault||fault>5u||injected||active_count||frozen)return false;injected=fault;return true; }
#endif
