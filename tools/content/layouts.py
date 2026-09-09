"""Host-only lowering of approved theme layouts into bounded native rectangles.

Applications keep their semantic nodes and service bindings. Every theme emits
its own complete scene table; no runtime layout parser or allocation is needed.
"""
from copy import deepcopy
from .tsx import KINDS, COLOR_ROLES

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

def apply_layout(scenes,theme):
    result=deepcopy(scenes)
    style=theme['layout']
    if style=='default':
        for scene in result:refine_scene(scene,theme,(4,24,212,148))
        return result
    font_h=theme['font']['height']
    # Each body rectangle is its own layout, not a recolor of the default shell.
    bodies={'ipod-photo':(0,22,220,154),'graphite':(10,42,200,108),
            'aurora':(52,38,160,132),'sunset':(12,46,196,104),'blueprint':(8,8,204,138)}
    headers={'ipod-photo':(0,0,220,22),'graphite':(12,8,196,26),
             'aurora':(52,7,160,25),'sunset':(12,8,196,30),'blueprint':(0,154,220,22)}
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
                elif style=='aurora':node['x']=52;node['w']=154 if any(n['kind']==9 for n in original) else 160
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
            if style=='ipod-photo':
                # Stock grouping: extra applications live under Extras.
                lookup=dict(zip(menu['items'],menu['targets']))
                extras=next((i for i,s in enumerate(result) if s['id']=='linnet.system.extras'),None)
                if extras is not None:
                    menu['items']=['Music','Photos','Extras','Settings','Now Playing']
                    menu['targets']=[lookup['Music'],lookup['Photos'],extras,lookup['Settings'],lookup['Now Playing']]
                    menu['count']=menu['item_count']=5
            elif style=='blueprint':place(menu,8,8,204,138)
        if scene['id']=='linnet.system.themes':
            listing=next(n for n in nodes if n['kind']==6)
            foot=next(n for n in nodes if n['kind']==3)
            if style=='ipod-photo':place(listing,0,22,210,132);place(foot,6,156,208,18)
            elif style=='graphite':place(listing,10,36,194,90);place(foot,12,132,196,18)
            elif style=='aurora':place(listing,52,36,154,104);place(foot,52,144,160,30)
            elif style=='sunset':place(listing,12,42,190,84);place(foot,12,132,196,20)
            elif style=='blueprint':place(listing,8,8,196,126);place(foot,8,136,204,16)
            foot['flags']=0
            bar=next(n for n in nodes if n['kind']==9);bar['y']=listing['y'];bar['h']=listing['h']
        if scene['id']=='linnet.system.now-playing':
            by_kind={}
            for node in nodes:by_kind.setdefault(node['kind'],[]).append(node)
            art=by_kind[14][0];title=next(n for n in nodes if n['text']=='Sample track')
            artist=next(n for n in nodes if n['text']=='Audio pending')
            status=next(n for n in nodes if n['text']=='Native playback shell')
            icon=by_kind[4][0];bar=by_kind[10][0]
            icon['flags']|=2
            if style=='ipod-photo':
                art['flags']|=2;status['flags']|=2
                place(title,10,46,200,22);title['flags']=CENTER
                place(artist,10,72,200,22);artist['flags']=CENTER;artist['fg']=color('foreground')
                place(bar,10,134,200,12)
                nodes.extend([text_node(title,'Track position',10,28,180,16),text_node(title,'Track album',10,98,200,22,CENTER),
                    text_node(title,'Track elapsed',10,151,90,22),text_node(title,'Track remaining',120,151,90,22,RIGHT)])
            elif style=='graphite':
                place(art,12,46,88,88);place(title,112,44,96,42);title['flags']=WRAP
                place(artist,112,90,96,40);artist['flags']=WRAP
                place(bar,12,143,196,7);place(status,12,133,196,17);status['flags']|=2
            elif style=='aurora':
                place(art,96,38,72,72);place(title,52,114,160,20);title['flags']=CENTER
                place(artist,52,135,160,20);artist['flags']=CENTER
                place(bar,52,161,160,6);status['flags']|=2
            elif style=='sunset':
                place(art,144,46,64,64);place(title,12,45,122,48);title['flags']=WRAP
                place(artist,12,116,196,21);place(bar,12,143,196,6);place(status,12,134,196,19);status['flags']|=2
            elif style=='blueprint':
                place(art,8,8,52,52);place(title,70,8,142,32);title['flags']=WRAP
                place(artist,70,43,142,20);place(bar,8,84,204,14);place(status,8,126,204,20)
                nodes.extend([text_node(title,'Track elapsed',8,104,95,18),text_node(title,'Track remaining',116,104,96,18,RIGHT)])
        if scene['id']=='linnet.system.video-controls':
            # Keep controls in their theme's chrome while video is fitted behind.
            for node in nodes:
                if node['kind']==16:place(node,bx,by,bw,bh)
        refine_scene(scene,theme,(bx,by,bw,bh))
        # Fixed clipping bounds remain a compiler invariant for every variant.
        for node in nodes:
            node['w']=max(1,min(node['w'],220-node['x']))
            node['h']=max(1,min(node['h'],176-node['y']))
        scene['count']=len(nodes)
    return result


def refine_scene(scene,theme,body):
    """Place service text and media explicitly rather than compressing baselines."""
    style=theme['layout'];x,y,w,h=body;bottom=y+h
    fh=theme['font']['height'];rh=theme['metrics']['row_height']
    nodes=scene['nodes'];sid=scene['id'].rsplit('.',1)[-1]
    texts=[n for n in nodes if n['kind']==3]
    listing=next((n for n in nodes if n['kind'] in (6,7,8)),None)
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
        for n in nodes:
            if n['kind']==5:
                size=min(n['w'],n['h']);place(n,n['x'],n['y'],size,size)
    elif sid=='update' and style=='sunset':
        for i,n in enumerate(texts):place(n,12,40+i*17,196,17);n['flags']=0
        place(listing,12,126,196,26)
    elif sid=='clock':
        for n in texts:
            if n['text']=='System clock':place(n,x+4,y+max(4,(h-5*fh-12)//2),w-8,2*fh+4);n['flags']=CENTER
            elif n['text']=='Clock source':place(n,x+4,bottom-3*fh-8,w-8,2*fh);n['flags']=WRAP
            else:place(n,x+4,bottom-fh,w-8,fh);n['flags']=CENTER
    elif sid=='clock-edit':
        if style=='graphite':y=36;h=bottom-y
        field_h=24 if style=='graphite' else 22 if style=='ipod-photo' else max(18,fh+3)
        list_h=max(field_h,((h-2*fh-8)//field_h)*field_h)
        place(listing,x,y,w-8,list_h)
        for n in texts:place(n,x+4,bottom-2*fh,w-8,2*fh);n['flags']=WRAP
    elif sid in ('display','battery'):
        place(listing,x,y,w,rh)
        for i,n in enumerate(texts):
            top=y+rh+8 if i==0 else bottom-(len(texts)-i)*(fh+5)
            place(n,x+4,top,w-8,fh);n['flags']=0
    elif sid in ('music-sound','music-queue'):
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
        place(surface,x,y,w,max(16,h-fh-18))
        place(bar,x,bottom-fh-13,w,5)
        for n in texts:place(n,x,bottom-fh,w,fh);n['flags']=0
    elif sid=='now-playing' and style not in ('ipod-photo','default'):
        title=next(n for n in texts if n['text']=='Sample track')
        artist=next(n for n in texts if n['text']=='Audio pending')
        status=next(n for n in texts if n['text']=='Native playback shell');status['flags']|=2
        art=next(n for n in nodes if n['kind']==14);bar=next(n for n in nodes if n['kind']==10)
        if style=='graphite':
            place(art,12,42,72,72);place(title,94,42,114,36);title['flags']=WRAP
            place(artist,94,82,114,36);artist['flags']=WRAP
        elif style=='aurora':
            place(art,104,38,56,56);place(title,52,99,160,fh);title['flags']=CENTER
            place(artist,52,119,160,fh);artist['flags']=CENTER
        elif style=='sunset':
            place(art,144,46,64,64);place(title,12,46,124,2*fh+4);title['flags']=WRAP
            place(artist,12,84,124,2*fh+4);artist['flags']=WRAP
        elif style=='blueprint':
            place(art,8,8,64,64);place(title,82,8,130,2*fh+4);title['flags']=WRAP
            place(artist,82,44,130,2*fh+4);artist['flags']=WRAP
            album=text_node(title,'Track album',8,84,204,fh,0,'muted');nodes.append(album)
        place(bar,x,bottom-5,w,5)
        elapsed=next((n for n in texts if n['text']=='Track elapsed'),None)
        remaining=next((n for n in texts if n['text']=='Track remaining'),None)
        if elapsed is None:elapsed=text_node(title,'Track elapsed',0,0,1,1);nodes.append(elapsed)
        if remaining is None:remaining=text_node(title,'Track remaining',0,0,1,1);nodes.append(remaining)
        place(elapsed,x,bottom-fh-11,(w-12)//2,fh);elapsed['flags']=0
        place(remaining,x+(w+12)//2,bottom-fh-11,(w-12)//2,fh);remaining['flags']=RIGHT
    if listing:
        for n in nodes:
            if n['kind']==9:n['y']=listing['y'];n['h']=listing['h']
    scene['count']=len(nodes)


def gate_features(scenes,features):
    """Keep stable scene slots while removing links into disabled services."""
    groups={
        'files':{'linnet.system.files'},
        'demo':{'local.example.notes'},
        'photos':{'linnet.system.photos','linnet.system.photos-grid','linnet.system.photos-viewer','linnet.system.photos-options'},
        'video':{'linnet.system.videos','linnet.system.video-player','linnet.system.video-controls'},
    }
    disabled={sid for feature,ids in groups.items() if not features.get(feature,feature!='demo') for sid in ids}
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
