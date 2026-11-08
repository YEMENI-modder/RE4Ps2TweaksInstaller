"""
Native menu installer with verified Parry V2/V3/V4 range ownership.

ANDROID/CHAQUOPY NOTE:
This is the ORIGINAL installer's patch() function, copied byte-for-byte
from Instalar-Portatil.py. Only choose_file() (Windows file dialog) and
main() (CLI entry point with input()/sys.argv) were removed, since
neither works on Android and neither is part of the actual patch logic.
Every check, hash comparison, and fail() condition below is UNCHANGED
from the original PC/Winlator tool — do not simplify or remove any of
these checks, they are what protects the user's ISO from corruption
when combined with other mods (e.g. Parry V2/V3/V4).
"""
import os,sys,json,hashlib,struct,time

def patch(data,region,root):
 def load(name):
  with open(os.path.join(root,'dados',name),'rb') as f:return f.read()
 def profile(tag):return json.loads(load(tag+'.json'))
 def fail(msg):raise ValueError(msg)
 def area(off,n):
  if off<0 or off+n>len(data):fail('Executavel truncado ou revisao diferente.')
  return data[off:off+n]
 def u(off):return struct.unpack('<I',area(off,4))[0]
 if len(data)<64 or data[:7]!=b'\x7fELF\x01\x01\x01' or struct.unpack_from('<H',data,18)[0]!=8:fail('Selecione o executavel PS2 extraido, nao a ISO inteira.')
 segments=[];ph=u(28);stride=struct.unpack('<H',area(42,2))[0];count=struct.unpack('<H',area(44,2))[0]
 if not(0<count<128 and stride>=32):fail('Program headers invalidos.')
 for i in range(count):
  at=ph+i*stride
  if u(at)==1:segments.append((u(at+8),u(at+4),u(at+16)))
 def off(va,n):
  for v,o,z in segments:
   if v<=va and va+n<=v+z:return o+va-v
  fail('Endereco do parry fora dos segmentos carregados.')
 protected=[];parry_hooks=[];magic=b'RE4PARRY_V2_META\0';at=data.find(magic)
 while at>=0:
  cave,size,n,version=struct.unpack('<4I',area(at+16,16))
  if at%4 or version!=2 or n not in [6,7] or not(0x2000<=size<0x20000) or off(cave+0x1a00,64+n*24)!=at:fail('Metadados do Parry V2/V3/V4 invalidos.')
  start=off(cave,size);block=bytearray(area(start,size));block[0x1a20:0x1a40]=bytes(32)
  if hashlib.sha256(block).digest()!=area(at+32,32):fail('A area do Parry V2/V3/V4 foi alterada. Nenhum arquivo foi modificado.')
  for i in range(n):
   entry=at+64+i*24;va,z=struct.unpack('<2I',area(entry,8))
   if z not in [4,8]:fail('Tamanho de gancho do parry invalido.')
   pos=off(va,z)
   if area(pos,z)!=area(entry+16,z):fail('Gancho do Parry V2/V3/V4 alterado por outro sistema.')
   parry_hooks.append((pos,z))
  protected.append((start,start+size));at=data.find(magic,at+len(magic))
 def overlap(o,n):return any(o<end and start<o+n for start,end in protected)
 def masked(o,n):
  b=bytearray(area(o,n))
  for start,end in protected:
   lo=max(o,start);hi=min(o+n,end)
   if lo<hi:b[lo-o:hi-o]=bytes(hi-lo)
  return bytes(b)
 def hooks(p):return all(area(g['offset'],4).hex()==g['new'] for g in p['menu_hooks'])
 tags=[region,region+'_alternativo'];profiles={tag:profile(tag) for tag in tags}
 suffixes=['','_menu_anterior','_v3menu','_v4menu','_v5menu','_v6menu','_v7menu','_v8menu','_v9menu','_v11menu','_v12menu','_v13menu','_v13_1menu','_v14menu','_v14_2menu','_v14_2_2menu','_v15pre','_v15_1menu','_v15_2menu','_v15_4menu','_v15_5menu','_v16menu','_v17menu','_v19_8menu']
 if region=='SLPM':suffixes=['','_v17menu','_v19_8menu']
 def version(tag,s):return profile(tag+('_perfil_anterior' if s=='_menu_anterior' else s))
 # Pair each known HUD with its exact menu and active hook addresses.
 # A Parry range may replace only zero padding, never known menu code.
 source=None
 for tag in tags:
  p=profiles[tag]
  if overlap(p['cave_offset'],p['size']):fail('Parry V2/V3/V4 sobrepoe a area ativa do HUD; esta combinacao precisa de outra relocacao.')
  current=area(p['cave_offset'],p['size']);men=masked(p['menu_offset'],p['menu_size'])
  for suffix in suffixes:
   if current==load(tag+suffix+'.bin') and men==load(tag+suffix+'_menu.bin') and hooks(version(tag,suffix)):
    source=tag;break
  if source:break
 if source is None and region=='SLPM':
  p=profiles[region]
  if not (area(p['cave_offset'],p['size'])==bytes(p['size']) and area(p['hook_offset'],8).hex()==p['hook_original'] and area(p['early_hook_offset'],8).hex()==p['early_original'] and all(area(g['offset'],4).hex()==g['original'] for g in p['menu_hooks'])):fail('Menu japones desconhecido.')
 elif source is None:
  p=profiles[region];current=area(p['cave_offset'],p['size']);hook=area(p['hook_offset'],8).hex();early=area(p['early_hook_offset'],8).hex()
  prev=load(region+'_anterior.bin');prev+=bytes(p['size']-len(prev))
  clean=current==bytes(p['size']) and hook==p['hook_original'] and early==p['early_original']
  legacy_bad_jump=early=='00930e0c00000000' and current==prev and area(p['cave_offset']-0x400,0x400)==bytes(0x400)
  old=hook==p['hook_original'] and ((early==p['hook_new'] and current in [prev,load(region+'_v1.bin')]) or legacy_bad_jump)
  hp_only=hook==p['hook_new'] and early==p['early_original'] and current in [load(region+'_v2.bin'),load(region+'_v3.bin')]
  native=all(area(g['offset'],4).hex()==g['original'] for g in p['menu_hooks'])
  if not(native and (clean or old or hp_only)):fail('Menu/HUD desconhecido. Apenas preenchimento zero pertencente a um Parry V2/V3/V4 verificado pode ser compartilhado.')
 # Keep the active cave when safe; otherwise migrate to an intact free or
 # known inactive cave. Never erase or relocate the Parry reserved block.
 target=None
 for tag in ([source] if source else [])+[t for t in tags if t!=source]:
  p=profiles[tag]
  if overlap(p['menu_offset'],p['menu_size']):continue
  content=area(p['menu_offset'],p['menu_size'])
  if content in [bytes(p['menu_size'])]+[load(tag+s+'_menu.bin') for s in suffixes]:target=tag;break
 if target is None:fail('Nao existe area livre segura para menu + Parry V2/V3/V4 nesta copia. Original preservado.')
 p=profiles[target]
 for g in p['guards']:
  if area(g['offset'],len(g['hex'])//2).hex()!=g['hex']:fail('Revisao diferente ou conflito no offset %X.'%g['offset'])
 hud=load(target+'.bin');menu=load(target+'_menu.bin')
 for b,size,digest in [(hud,p['size'],p['sha256_payload']),(menu,p['menu_size'],p['sha256_menu'])]:
  if len(b)!=size or hashlib.sha256(b).hexdigest()!=digest:fail('Dados do instalador corrompidos.')
 for field in ['sensitivity_hooks','retired_hooks']:
  for g in p[field]:
   accepted=set()
   for candidate in profiles.values():
    for old in candidate[field]:
     if old['offset']==g['offset']:accepted.update(old.get('accepted',[old['original'],old['new']]))
   if area(g['offset'],8).hex() not in accepted:fail('Gancho da sensibilidade/luneta desconhecido no offset %X.'%g['offset'])
 camera=load(target+'_camera.bin');cp=p['freecam'];ch=cp['hook']
 if len(camera)!=cp['size'] or hashlib.sha256(camera).hexdigest()!=cp['sha256']:fail('Dados da camera corrompidos.')
 current_camera=area(cp['offset'],cp['size']);current_hook=area(ch['offset'],8).hex()
 if overlap(cp['offset'],cp['size']):fail('Camera sobrepoe outra area reservada.')
 known_cameras=[camera] if region=='SLPM' else [camera,load(target+'_camera_v13.bin'),load(target+'_camera_v14.bin'),load(target+'_camera_v14_1.bin')]
 if not ((current_camera==bytes(cp['size']) and current_hook==ch['original']) or (current_camera in known_cameras and current_hook==ch['new'])):fail('Area ou gancho da camera possui outra modificacao. Original preservado.')
 sys.path.insert(0,os.path.abspath(root))
 import importlib.util
 def local_module(name):
  spec=importlib.util.spec_from_file_location('tweaks18_3_'+name,os.path.join(root,name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 prepare=local_module('RemoveWeaponSwap').prepare
 weapon_extension=(lambda result:result) if region=='SLPM' else prepare(data,p,load,target)
 install_extension=local_module('FilesUsed').install_extension
 extension=install_extension(data,p,load)
 result=bytearray(data)
 def put(o,b):
  if overlap(o,len(b)) or any(o<a+z and a<o+len(b) for a,z in parry_hooks):fail('Uma escrita do menu atingiria o Parry V2/V3/V4. Original preservado.')
  result[o:o+len(b)]=b
 put(p['cave_offset'],hud);put(p['menu_offset'],menu);put(cp['offset'],camera);put(ch['offset'],bytes.fromhex(ch['new']))
 for g in p['menu_hooks']+p['sensitivity_hooks']:put(g['offset'],bytes.fromhex(g['new']))
 for g in p['retired_hooks']:put(g['offset'],bytes.fromhex(g['original']))
 put(p['hook_offset'],bytes.fromhex(p['hook_new']));put(p['early_hook_offset'],bytes.fromhex(p['early_original']))
 assert len(result)==len(data)
 for start,end in protected:assert result[start:end]==data[start:end]
 result=weapon_extension(extension(bytes(result)))
 return bytes(result),p['serial']

# NOTE: the original main() (CLI entry point) and its __main__ guard were
# intentionally removed here. On Android, iso_handler.run_full_patch()
# calls patch() directly with data/region/root already resolved from the
# extracted ISO file and the app's bundled asset path — there is no
# interactive file picker or argv parsing on this platform.
