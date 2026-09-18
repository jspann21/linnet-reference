"""Host-only lowering of approved theme layouts into bounded native rectangles.

Applications keep their semantic nodes and service bindings. Every theme emits
its own complete scene table; no runtime layout parser or allocation is needed.
"""
from copy import deepcopy
from .tsx import COLOR_ROLES

TOKEN=0x10000
CENTER=8
RIGHT=16
WRAP=32

def color(name): return TOKEN+COLOR_ROLES.index(name)

def place(node,x,y,w,h):
    node.update(x=x,y=y,w=w,h=h)
    return node

def text_node(template,text,x,y,w,h,flags=0,fg='foreground'):
    node=deepcopy(template)
    node.update(kind=3,component='Text',x=x,y=y,w=w,h=h,fg=color(fg),bg=color('background'),
                flags=flags,count=0,resource=0xffffffff,index=0,text=text,items=[],targets=[],item_count=0,deps=4,canvas='')
    return node

def apply_layout(scenes,theme,compact=False):
    result=deepcopy(scenes)
    style=theme['layout']
    if style in ('default','minimal'):
        body=(0,20,220,156) if compact else (4,26 if style=='minimal' else 24,212,146 if style=='minimal' else 148)
        for scene in result:
            refine_scene(scene,theme,body)
            if style=='minimal':refine_minimal(scene,theme)
            refine_footers(scene,theme)
            align_scrollbars(scene,theme)
        return result
    font_h=theme['font']['height']
    # Each body rectangle is its own layout, not a recolor of the default shell.
    bodies={'ipod-photo':(0,22,220,154),'graphite':(10,42,200,108),
            'aurora':(34,38,178,132),'sunset':(12,46,196,104),'blueprint':(8,8,204,138)}
    headers={'ipod-photo':(0,0,220,22),'graphite':(0,0,220,26),
             'aurora':(34,7,178,25),'sunset':(0,0,220,30),'blueprint':(0,154,220,22)}
    bx,by,bw,bh=bodies[style]
    for scene in result:
        original=deepcopy(scene['nodes'])
        for node,old in zip(scene['nodes'],original):
            kind=node['kind']
            if kind==1: continue
            if kind==11:
                place(node,*headers[style])
                if style=='ipod-photo' and scene['id']=='linnet.system.home':node['text']='iPod'
                continue
            if kind==16 and old['x']==0 and old['y']==0 and old['w']==220 and old['h']==176:
                # Actual fullscreen video still owns the complete display.
                continue
            x=bx+(old['x']*bw)//220
            y=by+(max(0,old['y']-24)*bh)//152
            w=max(1,(old['w']*bw)//220)
            h=max(1,(old['h']*bh)//152)
            if kind in (3,12,13):h=max(h,font_h+(8 if kind in (12,13) else 0))
            place(node,x,min(y,176-h),min(w,220-x),min(h,176-y))
            if kind in (6,7,8):
                # Lists use all of their allotted rows; static footers retain space.
                if old['y']==24:
                    node['y']=by
                    node['h']=bh if old['h']>=148 else max(theme['metrics']['row_height'],bh-24)
                if style=='ipod-photo':
                    node['x']=0;node['w']=210 if any(n['kind']==9 for n in original) else 220
                    if old['y']==24:node['h']=154 if old['h']>=148 else 132
                elif style=='graphite':node['x']=10;node['w']=194 if any(n['kind']==9 for n in original) else 200
                elif style=='aurora':node['x']=34;node['w']=172 if any(n['kind']==9 for n in original) else 178
                elif style=='sunset':node['x']=12;node['w']=190 if any(n['kind']==9 for n in original) else 196
                elif style=='blueprint':node['x']=8;node['w']=196 if any(n['kind']==9 for n in original) else 204
            if kind==9:
                node['x']=210 if style=='ipod-photo' else bx+bw-4
                node['w']=10 if style=='ipod-photo' else 4
                listing=next((n for n in scene['nodes'] if n['kind'] in (6,7,8)),None)
                if listing:node['y']=listing['y'];node['h']=listing['h']
            if kind==3:node['flags']|=WRAP
        nodes=scene['nodes']
        if scene['id']=='linnet.system.update' and style=='graphite':
            lines=[n for n in nodes if n['kind']==3]
            for i,node in enumerate(lines):place(node,12,36+i*18,196,18);node['flags']=0
            menu=next(n for n in nodes if n['kind']==7);place(menu,10,126,200,26)
        if scene['id']=='linnet.system.home':
            menu=next(n for n in nodes if n['kind']==7)
            if style=='blueprint':place(menu,8,8,204,138)
        if scene['id']=='linnet.system.themes':
            listing=next(n for n in nodes if n['kind']==6)
            foot=next(n for n in nodes if n['kind']==3)
            if style=='ipod-photo':place(listing,0,22,210,132);place(foot,6,156,208,18)
            elif style=='graphite':place(listing,10,36,194,90);place(foot,12,132,196,18)
            elif style=='aurora':place(listing,34,36,172,104);place(foot,34,144,178,30)
            elif style=='sunset':place(listing,12,42,190,84);place(foot,12,132,196,20)
            elif style=='blueprint':place(listing,8,8,196,126);place(foot,8,136,204,16)
            foot['flags']=0
            bar=next(n for n in nodes if n['kind']==9);bar['y']=listing['y'];bar['h']=listing['h']
        refine_scene(scene,theme,(bx,by,bw,bh))
        refine_footers(scene,theme)
        if style=='ipod-photo':refine_ipod_photo(scene,theme)
        align_scrollbars(scene,theme)
        # Fixed clipping bounds remain a compiler invariant for every variant.
        for node in nodes:
            node['w']=max(1,min(node['w'],220-node['x']))
            node['h']=max(1,min(node['h'],176-node['y']))
        scene['count']=len(nodes)
    return result


def align_scrollbars(scene,theme):
    listing=next((n for n in scene['nodes'] if n['kind'] in (6,7,8) and n['flags']&1),None)
    if not listing:return
    for bar in scene['nodes']:
        if bar['kind']!=9:continue
        if theme['layout']=='ipod-photo':
            place(bar,210,listing['y'],10,listing['h'])
            continue
        inset=2 if theme['layout']=='ipod-photo' else 0
        bar['y']=listing['y']+inset
        bottom={'graphite':150,'aurora':170,'sunset':150,'blueprint':146}.get(theme['layout'],172)
        bar['h']=max(1,bottom-bar['y'])
        for node in scene['nodes']:
            if node['kind']==3:node['w']=min(node['w'],bar['x']-node['x']-4)
        listing['w']=min(listing['w'],bar['x']-listing['x']-(3 if inset else 2))


def refine_footers(scene,theme):
    """Keep supporting text on one bottom grid, above each theme's chrome."""
    sid=scene['id'].rsplit('.',1)[-1]
    keys={'themes':{'Theme status'},'clock':{'Clock source'},
          'clock-edit':{'Clock edit hint'},'sleep-timer':{'Sleep timer status'},'music-search':{'Search controls'}}
    texts=[n for n in scene['nodes'] if n['kind']==3]
    if sid in keys:foot=[n for n in texts if n['text'] in keys[sid]]
    elif sid in ('display','battery','shutdown'):foot=texts[1:]
    elif sid in ('music','music-queue','music-sound','video-controls'):foot=texts
    else:return
    if not foot:return
    style=theme['layout']
    x,w,bottom={'aurora':(38,170,172),'graphite':(14,192,150),
                'sunset':(16,188,150),'blueprint':(8,204,150)}.get(style,(6,208,172))
    if len(foot)>1:
        foot[0]['text']='  '.join(n['text'] for n in foot)
        for n in foot[1:]:n['flags']|=2
    height=36 if sid in ('clock','clock-edit','music-search','display','battery','shutdown') else 24
    if sid=='themes':height=12
    place(foot[0],x,bottom-height,w,height);foot[0]['flags']=64
    for n in scene['nodes']:
        if n['kind'] in (6,7) and n['y']<bottom-height and n['y']+n['h']>bottom-height-4:
            n['h']=max(18,bottom-height-4-n['y'])
    listing=next((n for n in scene['nodes'] if n['kind'] in (6,7)),None)
    if listing:
        for n in scene['nodes']:
            if n['kind']==9:n['h']=min(n['h'],listing['h'])


def refine_scene(scene,theme,body):
    """Place service text and media explicitly rather than compressing baselines."""
    style=theme['layout'];x,y,w,h=body;bottom=y+h
    fh=theme['font']['height'];rh=theme['metrics']['row_height']
    nodes=scene['nodes'];sid=scene['id'].rsplit('.',1)[-1]
    texts=[n for n in nodes if n['kind']==3]
    listing=next((n for n in nodes if n['kind'] in (6,7,8)),None)
    if listing and listing['kind']==6:rh=max(18,fh+5)
    if scene['id']=='local.example.notes':
        top_h=2*fh if style=='aurora' else fh
        for n in texts:place(n,x+4,y,w-8,top_h);n['flags']=WRAP
        toast_h=fh+6;dialog_h=fh+10;toast_y=bottom-toast_h;dialog_y=toast_y-4-dialog_h
        visual_y=y+top_h+5;visual_h=max(8,dialog_y-5-visual_y);half=(w-12)//2
        for n in nodes:
            if n['kind']==17:place(n,x+4,visual_y,half,visual_h)
            elif n['kind']==15:place(n,x+8+half,visual_y,half,visual_h)
            elif n['kind']==12:place(n,x if style=='aurora' else x+4,dialog_y,w if style=='aurora' else w-8,dialog_h)
            elif n['kind']==13:place(n,x+4,toast_y,w-8,toast_h)
    elif sid=='about':
        # Preserve theme chrome while centering the shared brand mask.
        art_h=min(104,h-2*fh-14);art_w=art_h*68//104
        art=next(n for n in nodes if n['kind']==17)
        place(art,x+(w-art_w)//2,y+2,art_w,art_h)
        for i,n in enumerate(texts):
            place(n,x,y+art_h+7+i*(fh+4),w,fh);n['flags']=CENTER
    elif sid=='update' and style=='sunset':
        for i,n in enumerate(texts):place(n,12,40+i*17,196,17);n['flags']=0
        place(listing,12,126,196,26)
    elif sid=='clock':
        clock_h=2*fh+4
        row_h=max(20,fh+6)
        place(listing,x,y+clock_h+8,w,2*row_h)
        for n in texts:
            if n['text']=='System clock':place(n,x+4,y,w-8,clock_h);n['flags']=CENTER
            elif n['text']=='Clock source':place(n,x+4,bottom-2*fh,w-8,2*fh);n['flags']=WRAP
    elif sid=='clock-edit':
        if style=='graphite':y=36;h=bottom-y
        field_h=24 if style=='graphite' else 22 if style=='ipod-photo' else max(18,fh+3)
        list_h=max(field_h,((h-2*fh-8)//field_h)*field_h)
        place(listing,x,y,w-8,list_h)
        for n in texts:place(n,x+4,bottom-2*fh,w-8,2*fh);n['flags']=WRAP
    elif sid=='sleep-timer':
        place(listing,listing['x'],y,listing['w'],max(rh,((h-32)//rh)*rh))
        for n in texts:place(n,x+4,bottom-26,w-8,26);n['flags']=WRAP
    elif sid in ('display','battery','shutdown'):
        list_h=max(50,2*rh) if sid=='shutdown' else rh
        place(listing,x,y,w,list_h)
        note_gap=max(50,2*rh)-2*rh+8
        for i,n in enumerate(texts):
            top=y+(2*rh if sid=='shutdown' else rh)+note_gap if i==0 else bottom-(len(texts)-i)*(fh+5)
            place(n,x+4,top,w-8,fh);n['flags']=0
    elif sid in ('music','music-sound','music-queue'):
        footer_h=fh if sid=='music-sound' else 2*fh
        place(listing,listing['x'],y,listing['w'],max(rh,((h-footer_h-8)//rh)*rh))
        for n in texts:place(n,x+4,bottom-footer_h,w-8,footer_h);n['flags']=WRAP
    elif sid=='music-search':
        prefix=next(n for n in texts if n['text']=='Search prefix')
        footer=next(n for n in texts if n['text']=='Search controls')
        prefix_y=y-4 if style in ('graphite','sunset') else y
        place(prefix,x+4,prefix_y,w-8,fh);prefix['flags']=0
        top=prefix_y+fh+3;foot=bottom-2*fh
        place(listing,listing['x'],top,listing['w'],max(rh,((foot-top-4)//rh)*rh))
        place(footer,x+4,foot,w-8,2*fh);footer['flags']=WRAP
    elif sid=='photos-grid':
        place(listing,x,y,w,h)
        for n in texts:place(n,x+8,y+(h-2*fh)//2,w-16,2*fh);n['flags']=CENTER
    elif sid=='video-controls':
        surface=next(n for n in nodes if n['kind']==16)
        bar=next(n for n in nodes if n['kind']==10)
        # Keep the full authoring canvas behind the controls. Scaling this surface
        # resamples every video frame on ARM7 and defeats direct presentation.
        place(surface,0,0,220,176)
        place(bar,x,bottom-fh-13,w,5)
        for n in texts:place(n,x,bottom-fh,w,fh);n['flags']=0
    elif sid=='now-playing':
        title=next(n for n in texts if n['text']=='Sample track')
        artist=next(n for n in texts if n['text']=='Audio pending')
        status=next(n for n in texts if n['text']=='Native playback shell')
        art=next(n for n in nodes if n['kind']==14)
        bar=next(n for n in nodes if n['kind']==10)
        # Metadata owns stable lines; notices never displace it or disappear.
        inset=6 if style=='ipod-photo' else 4
        left=x+inset;width=w-2*inset;top=y+(2 if h<120 else 4)
        if style=='ipod-photo':
            # Photo-era composition: position above art, metadata to its right.
            header=next(n for n in nodes if n['kind']==11);header['text']='Now Playing'
            left=10;width=200
            place(art,10,46,70,70)
            nodes.append(text_node(title,'Track position',10,29,200,fh))
            place(title,90,50,120,2*fh);title['flags']=WRAP
            place(artist,90,86,120,fh);artist['flags']=0;artist['fg']=color('foreground')
            nodes.append(text_node(title,'Track album',90,106,120,fh))
        elif style=='aurora':
            place(art,left+(width-32)//2,top,32,32)
            place(title,left,top+36,width,2*fh);title['flags']=WRAP
            place(artist,left,top+38+2*fh,width,fh);artist['flags']=CENTER
        else:
            size=56 if h<120 else 64
            lines=2 if h<120 else 3
            place(art,left,top,size,size)
            place(title,left+size+8,top,width-size-8,lines*fh);title['flags']=WRAP
            place(artist,left+size+8,top+lines*fh+4,width-size-8,2*fh);artist['flags']=WRAP
            if h>=138:
                nodes.append(text_node(title,'Track album',left,top+size+8,width,fh,0,'muted'))
        place(status,left,bottom-2*fh-14,width,fh);status['flags']=0;status['fg']=color('muted')
        place(bar,left,bottom-fh-10,width,4)
        if style=='ipod-photo':
            place(status,left,124,width,fh)
            place(bar,left,142,width,10)
        nodes.extend([text_node(title,'Track elapsed',left,bottom-fh-2,(width-12)//2,fh),
                      text_node(title,'Track remaining',left+(width+12)//2,bottom-fh-2,(width-12)//2,fh,RIGHT)])
    if listing:
        for n in nodes:
            if n['kind']==9:n['y']=listing['y'];n['h']=listing['h']
    scene['count']=len(nodes)


def refine_minimal(scene,theme):
    nodes=scene['nodes'];fh=theme['font']['height']
    for n in nodes:
        if n['kind']==11:place(n,0,2,220,20)
        elif n['kind'] in (4,5,14):n['flags']|=2
        elif n['kind']==2:n['bg']=color('background');n['flags']&=~4
    if scene['id']=='linnet.system.now-playing':
        for n in nodes:
            if n['text']=='Sample track':place(n,8,34,204,2*fh);n['flags']=WRAP
            elif n['text']=='Audio pending':place(n,8,68,204,2*fh);n['flags']=WRAP
            elif n['text']=='Track album':place(n,8,102,204,fh)
    scene['count']=len(nodes)


def refine_ipod_photo(scene,theme):
    """Photo-style chrome and content grid in the authoring coordinate space."""
    nodes=scene['nodes'];sid=scene['id'].rsplit('.',1)[-1]
    fh=theme['font']['height'];rh=22
    texts=[n for n in nodes if n['kind']==3]
    listing=next((n for n in nodes if n['kind'] in (6,7,8)),None)
    scroll=next((n for n in nodes if n['kind']==9),None)
    header=next((n for n in nodes if n['kind']==11),None)
    if header:
        place(header,0,0,220,21)
        names={'home':'iPod','about':'About','display':'Backlight Timer',
               'photos-options':'Slideshow Settings','music-sound':'EQ',
               'clock-edit':'Date & Time','music-options':'Playback Options'}
        if sid in names:header['text']=names[sid]
    if listing:
        # White edge at the right keeps the thumb and chevrons inside the LCD.
        top=21 if listing['y']<=24 else listing['y']
        bottom=min(176,listing['y']+listing['h']+1)
        place(listing,0,top,220,max(rh,((bottom-top)//rh)*rh))
        if listing['kind']==8:place(listing,0,21,210,155)
    if sid=='settings' and listing:
        labels={'About Linnet':'About','Display':'Backlight Timer','Clock':'Date & Time'}
        listing['items']=[labels.get(label,label) for label in listing['items']]
    elif sid=='now-playing':
        title=next(n for n in texts if n['text']=='Sample track')
        artist=next(n for n in texts if n['text']=='Audio pending')
        album=next(n for n in texts if n['text']=='Track album')
        # A single baseline for each field matches the original player layout.
        for n,y in ((title,47),(artist,72),(album,97)):
            place(n,10,y,200,fh);n['flags']=0;n['fg']=color('foreground')
        position=next(n for n in texts if n['text']=='Track position');place(position,10,29,200,fh)
        art=next(n for n in nodes if n['kind']==14);place(art,10,46,70,70)
        notice=next(n for n in texts if n['text']=='Native playback shell');place(notice,10,115,200,fh)
        bar=next(n for n in nodes if n['kind']==10);place(bar,11,134,198,11)
        for n in texts:
            if n['text']=='Track elapsed':place(n,10,150,94,fh)
            elif n['text']=='Track remaining':place(n,116,150,94,fh)
    elif sid=='themes' and listing:
        place(listing,0,21,220,132)
        for n in texts:place(n,6,155,208,17)
    elif sid in ('display','battery','shutdown','music','music-queue','music-sound','music-search','clock-edit','clock'):
        for n in texts:
            n['x']=6;n['w']=208
            n['h']=min(n['h'],172-n['y'])
            if n['h']<fh:n['y']=172-fh;n['h']=fh
    elif sid=='photos-viewer':
        surface=next(n for n in nodes if n['kind']==15);place(surface,0,21,220,155)
    elif sid=='cover-flow':
        surface=next(n for n in nodes if n['kind']==17);place(surface,0,0,220,140)
        for n in texts:
            place(n,4,141 if n['text']=='Cover Flow album' else 158,212,fh)
            n['flags']=0
    if sid in ('music','music-queue','music-sound') and listing:
        place(listing,0,21,220,154)
        for n in texts:n['flags']|=2
    if scroll and listing:
        place(scroll,210,listing['y'],10,listing['h'])
    scene['count']=len(nodes)


def feature_enabled(features, name):
    return features.get(name, name != 'demo')


def gate_features(scenes,features):
    """Keep stable scene slots while removing links into disabled services."""
    groups={
        'cover_flow':{'linnet.system.cover-flow'},
        'files':{'linnet.system.files'},
        'demo':{'local.example.notes'},
        'photos':{'linnet.system.photos','linnet.system.photos-grid','linnet.system.photos-viewer','linnet.system.photos-options'},
        'video':{'linnet.system.videos','linnet.system.video-player','linnet.system.video-controls'},
        'themes':{'linnet.system.themes'},
    }
    disabled={sid for feature,ids in groups.items() if not feature_enabled(features,feature) for sid in ids}
    enabled=[scene['id'] not in disabled for scene in scenes]
    for scene in scenes:
        for node in scene['nodes']:
            if not node['targets']:continue
            keep=[i for i,target in enumerate(node['targets']) if target>=len(scenes) or enabled[target]]
            node['items']=[node['items'][i] for i in keep]
            node['targets']=[node['targets'][i] for i in keep]
            node['count']=node['item_count']=len(keep)
            node['index']=min(node['index'],max(0,len(keep)-1))
    return sum(1<<i for i,available in enumerate(enabled) if available)
