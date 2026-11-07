"""Japanese regional installer: exact native guards, owned code and ELF segment checks."""
import struct,json,hashlib,os

def patch(data,region,root):
 root=os.path.abspath(root)
 def load(name):
  with open(os.path.join(root,'dados',name),'rb') as f:return f.read()
 def u(o):
  if o<0 or o+4>len(data):raise ValueError('Executavel truncado.')
  return struct.unpack_from('<I',data,o)[0]
 def h(o):return struct.unpack_from('<H',data,o)[0]
 def check(ok,msg):
  if not ok:raise ValueError(msg+' Original preservado.')
 check(len(data)>=64 and data[:7]==b'\x7fELF\x01\x01\x01' and h(18)==8,'Selecione o ELF extraido da ISO')
 ph=u(28);stride=h(42);count=h(44);check(stride==32 and 0<count<120,'Program headers invalidos')
 segs=[struct.unpack_from('<8I',data,ph+i*stride) for i in range(count)]
 def off(va,n=8):
  for t,fo,v,pa,fs,ms,fl,al in segs:
   if t==1 and v<=va and va+n<=v+fs:return fo+va-v
  raise ValueError('Endereco fora dos segmentos ELF.')
 protected=[];parryhooks=[];start=0;magic=b'RE4PARRY_V2_META\0'
 while True:
  at=data.find(magic,start)
  if at<0:break
  start=at+len(magic);cave,size,n,ver=struct.unpack_from('<4I',data,at+16)
  check(ver==2 and n in [6,7] and 0x2000<=size<0x20000,'Metadados Parry invalidos');pos=off(cave,size);check(off(cave+0x1a00,64+n*24)==at,'Metadados Parry fora da area')
  b=bytearray(data[pos:pos+size]);b[0x1a20:0x1a40]=bytes(32);check(hashlib.sha256(b).digest()==data[at+32:at+64],'Codigo Parry alterado')
  for i in range(n):
   entry=at+64+i*24;va,z=struct.unpack_from('<2I',data,entry);check(z in [4,8],'Gancho Parry invalido');o=off(va,z);check(data[o:o+z]==data[entry+16:entry+16+z],'Gancho Parry alterado');parryhooks.append((o,o+z))
  protected.append((pos,pos+size))
 def overlap(o,n,ranges):return any(o<b and a<o+n for a,b in ranges)
 profiles=[json.loads(load('SLPM'+alt+'.json')) for alt in ['', '_alternativo']];selected=None
 for active in profiles:
  if all(data[g['offset']:g['offset']+len(g['new'])//2].hex()==g['new'] for g in active['menu_hooks']):
   active_tag='SLPM'+('_alternativo' if active['menu_offset']<0x2a0000 else '')
   check(data[active['menu_offset']:active['menu_offset']+active['menu_size']]==load(active_tag+'_menu.bin'),'Menu ativo alterado')
   check(data[active['cave_offset']:active['cave_offset']+active['size']]==load(active_tag+'.bin'),'HUD ativo alterado')

 for p in profiles:
  code=[(p['cave_offset'],load('SLPM.bin')),(p['menu_offset'],load('SLPM'+('_alternativo' if p['menu_offset']<0x2a0000 else '')+'_menu.bin')),(p['freecam']['offset'],load('SLPM_camera.bin'))]
  if any(overlap(o,len(b),protected) for o,b in code):continue
  if all(data[o:o+len(b)] in [b,bytes(len(b))] for o,b in code):selected=p;break
 check(selected is not None,'Areas do menu ocupadas por outra modificacao');p=selected;tag='SLPM'+('_alternativo' if p['menu_offset']<0x2a0000 else '')
 changes=[]
 def put(o,b):
  check(o>=0 and o+len(b)<=len(data),'Escrita fora do ELF');check(not overlap(o,len(b),protected+parryhooks),'Conflito com o Parry');changes.append((o,b))
 for g in p['guards']:check(data[g['offset']:g['offset']+len(g['hex'])//2].hex()==g['hex'],'Revisao japonesa diferente no offset %X'%g['offset'])
 for suffix,offset,size,digest in [('.bin',p['cave_offset'],p['size'],p['sha256_payload']),('_menu.bin',p['menu_offset'],p['menu_size'],p['sha256_menu']),('_camera.bin',p['freecam']['offset'],p['freecam']['size'],p['freecam']['sha256'])]:
  b=load(tag+suffix);check(len(b)==size and hashlib.sha256(b).hexdigest()==digest,'Dados do pacote corrompidos');put(offset,b)
 hooklist=p['menu_hooks']+p['sensitivity_hooks']+[p['freecam']['hook']]+[dict(offset=p['hook_offset'],original=p['hook_original'],new=p['hook_new'])]
 for g in hooklist:
  z=len(g['original'])//2;accepted=[g['original'],g['new']]
  for pp in profiles:
   candidates=pp['menu_hooks']+pp['sensitivity_hooks']+[pp['freecam']['hook']]+[dict(offset=pp['hook_offset'],new=pp['hook_new'])]
   accepted.extend(q['new'] for q in candidates if q['offset']==g['offset'])
  check(data[g['offset']:g['offset']+z].hex() in accepted,'Gancho japones ocupado no offset %X'%g['offset']);put(g['offset'],bytes.fromhex(g['new']))
 check(data[p['early_hook_offset']:p['early_hook_offset']+8].hex()==p['early_original'],'Gancho antecipado ocupado')
 for g in p['retired_hooks']:check(data[g['offset']:g['offset']+8].hex()==g['original'],'Luneta possui outra modificacao')
 cp=p['files_used'];body=load(tag+'_files.bin');check(len(body)==cp['filesz'] and hashlib.sha256(body).hexdigest()==cp['sha256'],'Catalogo corrompido');existing=None;core=cp['filesz'];end=cp['reserve_end']
 for i,s in enumerate(segs):
  t,fo,va,pa,fs,ms,flags,align=s
  if t!=1:continue
  if va==cp['base']:
   check(existing is None and (pa,fs,ms,flags,align)==(va,cp['filesz'],cp['memsz'],7,4096) and fo+fs<=len(data),'Segmento japones desconhecido')
   old=bytearray(data[fo:fo+fs]);old[0x2010:0x2014]=bytes(4);check(bytes(old)==body,'Catalogo japones alterado');existing=(ph+i*stride,fo)
  else:
   core+=fs;check(not (va<end and cp['base']<va+ms),'Segmento ocupa a reserva do menu')
 for g in cp['hooks']:
  check(data[g['offset']:g['offset']+8].hex() in ([g['new']] if existing else [g['original']]),'Gancho do catalogo ocupado');put(g['offset'],bytes.fromhex(g['new']))
 for hi,lo,reg in [(cp['heap']['startup_hi'],cp['heap']['startup_lo'],4),(cp['heap']['arena_hi'],cp['heap']['arena_lo'],2)]:
  w,w2=u(hi),u(lo);check(w>>16==0x3c00|reg and w2>>16==0x2400|(reg<<5)|reg,'Inicializacao da RAM diferente');v=((w&65535)<<16)+((w2&65535)-65536 if w2&32768 else w2&65535);check(0x4a0000<=v<=end,'RAM reservada por outra modificacao');put(hi,struct.pack('<I',w&0xffff0000|((end+32768)>>16)));put(lo,struct.pack('<I',w2&0xffff0000|(end&65535)))
 for o in [cp['heap']['sbrk']]+cp['heap']['symbols']:check(0x4a0000<=u(o)<=end,'Fim do executavel diferente');put(o,struct.pack('<I',end))
 out=bytearray(data)
 for o,b in changes:out[o:o+len(b)]=b
 if existing:slot,fo=existing
 else:
  slot=ph+count*stride;check(slot+32<=0x1000 and not any(data[slot:slot+32]),'Sem program header livre');fo=(len(out)+4095)&~4095;out+=bytes(fo+cp['filesz']-len(out));struct.pack_into('<H',out,44,count+1);struct.pack_into('<8I',out,slot,1,fo,cp['base'],cp['base'],cp['filesz'],cp['memsz'],7,4096)
 out[fo:fo+len(body)]=body;struct.pack_into('<I',out,fo+0x2010,core)
 return bytes(out),p['serial']
