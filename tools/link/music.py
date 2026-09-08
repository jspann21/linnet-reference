"""Bounded development music controls; mutations are sent once after identity check."""
import struct
from .identity import decode
from .protocol import Command

def command(session,identity,action,*,path=None,sample=None):
    if action.endswith('-state'):
        schema={
            'video-state':(Command.VIDEO_STATE,b'VIT6',('magic','version','phase','error','active','pending','paused','next_frame','frame_count','front_frame','read_ops','read_bytes','prepared','presented','late_frames','max_late_samples','max_prepare_us','queued_frames','max_queued_frames','audio_underruns','audio_silence_frames','audio_fault','submitted_samples','revision')),
            'player-timing-state':(Command.PLAYER_TIMING_STATE,b'PMT4',('magic','version','decode_calls','decode_us','decode_max_us','dsp_calls','dsp_frames','dsp_us','dsp_max_us')),
            'audio-state':(Command.AUDIO_STATE,b'AUD4',('magic','version','rate','queued','free_frames','consumed','submitted','interrupts','underruns','silence_frames','fault','playing','paused','initialized','last_irq_us','max_irq_us','volume_db_tenths')),
            'player-state':(Command.PLAYER_STATE,b'PLR4',('magic','phase','error','generation','rate','decoded','rendered','underruns','frames_low','frames_high')),
            'library-state':(Command.LIBRARY_STATE,b'LIB4',('magic','version','phase','error','tracks','groups','verified_bytes','revision')),
            'photos-state':(Command.PHOTOS_STATE,b'PHT5',('magic','version','phase','error','active','ready','pending','view','file_size','verify_at','data_at','verify_crc','metadata_crc','verified_photos','verified_levels','verified_tiles','photo_index','visible_tiles','revision','navigation')),
        }
        operation,magic,names=schema[action]
        raw=session.request(operation)
        if action=='photos-state':
            version=struct.unpack_from('<I',raw,4)[0] if len(raw)>=8 else 0
            if (len(raw),version)==(128,2):
                names+=('frame_valid','frame_complete','slide_armed','slide_at_us','now_us','view_started_us','frame_ready_us','io_started_us','max_open_us','max_read_us','render_us','jpeg_us')
            elif (len(raw),version)!=(80,1):raise RuntimeError('Malformed photo state reply')
        if action=='video-state':
            version=struct.unpack_from('<I',raw,4)[0] if len(raw)>=8 else 0
            if (len(raw),version)==(128,2):
                names+=('max_io_us','max_record_read_us','max_record_crc_us','max_payload_crc_us','max_decode_us','max_frame_crc_us','max_step_us','min_audio_queued')
            elif (len(raw),version)!=(96,1):raise RuntimeError('Malformed video state reply')
        if action=='player-timing-state':
            version=struct.unpack_from('<I',raw,4)[0] if len(raw)>=8 else 0
            if (len(raw),version) in ((48,2),(60,3),(80,4)):
                names+=('runtime_calls','runtime_us','runtime_max_us')
                if version>=3:names+=('music_us','storage_us','link_us')
                if version>=4:names+=('clock_hz','cache_control','cache_priority','idle_us','clock_source')
            elif (len(raw),version)!=(36,1):
                raise RuntimeError('Malformed player timing reply')
        if action=='audio-state':
            version=struct.unpack_from('<I',raw,4)[0] if len(raw)>=8 else 0
            if (len(raw),version)==(80,2):
                names+=('fifo_empty_irqs','max_completion_interval_us','max_completion_late_us')
            elif (len(raw),version)!=(68,1):
                raise RuntimeError('Malformed music state reply')
        if action=='player-state' and len(raw)==64:
            names+=('next_phase','next_error','gapless_joins','missed_joins','position_low','position_high')
        expected=64 if action=='library-state' else len(names)*4
        if len(raw)!=expected or raw[:4]!=magic:raise RuntimeError('Malformed music state reply')
        state=dict(zip(names,struct.unpack('<'+'I'*len(names),raw[:len(names)*4])))
        for key in ('volume_db_tenths','error'):
            if key in state and state[key]>=0x80000000:state[key]-=0x100000000
        if action=='library-state':state['library_sha256']=raw[32:].hex()
        if action=='player-state':state['frames']=state.pop('frames_low')|(state.pop('frames_high')<<32)
        if 'position_low' in state:state['position']=state.pop('position_low')|(state.pop('position_high')<<32)
        return dict(identity=identity,state=state)
    confirmed=decode(session.status())
    if any(confirmed[key]!=identity[key] for key in ('target_id','build_id','generation')):
        raise RuntimeError('Device identity changed during music preflight')
    generation=identity['generation']
    if action=='player-open':
        encoded=path.encode('ascii')
        if not encoded.startswith(b'/') or len(encoded)>255 or b'\0' in encoded:
            raise ValueError('Player path must be an absolute ASCII filesystem path of at most255 bytes')
        operation=Command.PLAYER_OPEN;payload=struct.pack('<I',generation)+encoded+b'\0';value=0
    else:
        value={'player-pause':1,'player-resume':2,'player-stop':3,'player-seek':4}[action]
        operation=Command.PLAYER_CONTROL;payload=struct.pack('<II',generation,value)
        if value==4:
            if sample is None or not 0<=sample<=0xffffffffffffffff:raise ValueError('Sample must be an unsigned64-bit position')
            payload+=struct.pack('<Q',sample)
    reply=session.request(operation,payload)
    if reply!=struct.pack('<II',generation,value):
        session.poisoned = True
        from .session import AmbiguousCommand
        raise AmbiguousCommand('Unexpected music mutation acknowledgement; inspect state before further action')
    return dict(identity=identity,accepted=action)
