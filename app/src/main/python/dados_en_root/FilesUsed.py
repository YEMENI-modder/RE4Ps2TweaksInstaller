"""Verified Files Used + feature extension; preserves ESR/KEY and existing file offsets."""
import struct,hashlib,json

def install_extension(data,p,load):
 cp=p['files_used'];region=p['serial'].split('_')[0];tag=region+('_alternativo' if p['menu_offset']<0x2a0000 else '');payload=load(tag+'_files.bin')
 def fail(msg):raise ValueError(msg+' Original preservado.')
 def u(o):return struct.unpack_from('<I',data,o)[0]
 if len(payload)!=cp['filesz'] or hashlib.sha256(payload).hexdigest()!=cp['sha256']:fail('Dados da extensao corrompidos')
 candidates=json.loads(load('compat_esr_checkpoint.json')).get(region,[]);verified_end=0;ph=u(28);stride,n=struct.unpack_from('<HH',data,42);existing=None;core=0;old_end=0;esr_count=0;plaga_end=0;plaga_count=0
 for i in range(n):
  at=ph+i*stride;t,fo,va,pa,fs,ms,flags,align=struct.unpack_from('<8I',data,at)
  if t!=1:continue
  core+=fs
  if va<0x4f9000 and 0x4f8000<va+ms:
   profiles=json.loads(load('compat_plaga_forge.json')).get(region,[]);plaga_count+=1
   if plaga_count!=1 or (va,pa,fs,ms,flags,align)!=(0x4f8000,0x4f8000,4096,4096,7,4096) or fo+fs>len(data):fail('Segmento PLAGA FORGE invalido')
   normalized=bytearray(data[fo:fo+fs]);normalized[0xc00:0xe20]=bytes(544)
   match=next((q for q in profiles if hashlib.sha256(normalized).hexdigest()==q['sha256']),None)
   if not match:fail('Codigo PLAGA FORGE desconhecido')
   valid=set(match['ids'])
   for ident in range(272):
    value=struct.unpack_from('<H',data,fo+0xc00+ident*2)[0]
    if (ident in valid and not 1<=value<=999) or (ident not in valid and value):fail('Limites PLAGA FORGE invalidos')
   for hk in match['patches']:
    offset=hk['va']-0xff000;expected=bytes.fromhex(hk['new'])
    if data[offset:offset+len(expected)]!=expected:fail('Gancho PLAGA FORGE alterado')
   plaga_end=match['limit']
  if va==0x4f0000:
   match=next((c for c in candidates if fs==ms==c['size'] and fo+fs<=len(data) and hashlib.sha256(data[fo:fo+fs]).hexdigest()==c['sha256']),None)
   if match is None:fail('Segmento ESR desconhecido')
   esr_count+=1
   if esr_count!=1 or (pa,flags,align)!=(va,7,4096):fail('Segmento ESR duplicado ou invalido')
   for h in match['hooks']:
    o=h['va']-0xff000;b=bytes.fromhex(h['new'])
    if data[o:o+len(b)]!=b:fail('Gancho ESR alterado')
   verified_end=match['limit']
  if va==cp['base']:
   if existing or (pa,flags,align)!=(va,7,4096) or fo+fs>len(data):fail('Segmento da extensao invalido')
   blob=bytearray(data[fo:fo+fs]);blob[0x2010:0x2014]=bytes(4);allowed=[]
   if (fs,ms)==(cp['filesz'],cp['memsz']):allowed=[payload,load(tag+'_files_v19_4.bin'),load(tag+'_files_v19_4_1.bin'),load(tag+'_files_v19_4_2.bin'),load(tag+'_files_v19_4_3.bin'),load(tag+'_files_v19_4_4.bin'),load(tag+'_files_v19_5.bin'),load(tag+'_files_v19_6.bin'),load(tag+'_files_v19_7.bin'),load(tag+'_files_v19_8.bin'),load(tag+'_files_v19_9.bin')]
   if (fs,ms)==(0x33000,0x38000):allowed=[load(tag+'_files_v18_6.bin'),load(tag+'_files_v19.bin'),load(tag+'_files_v19_1.bin'),load(tag+'_files_v19_2.bin'),load(tag+'_files_v19_3.bin')]
   if (fs,ms)==(0x30000,0x38000):allowed=[load(tag+'_files_v18.bin'),load(tag+'_files_v18_3.bin'),load(tag+'_files_v18_4.bin'),load(tag+'_files_v18_5.bin')]
   for suffix,memsz in [('_files_v17.bin',0x2c000),('_files_v16.bin',0x40000),('_files_v14.bin',0x40000)]:
    if region=='SLPM' and suffix!='_files_v17.bin':continue
    if fs==0x3000 and ms==memsz:allowed.append(load(tag+suffix))
   if bytes(blob) not in allowed:fail('Codigo da extensao desconhecido')
   existing=(at,fo,fs);old_end=va+ms
  elif va<cp['reserve_end'] and cp['base']<va+ms:fail('Outra modificacao ocupa a extensao')
 for h in cp['hooks']:
  size=len(h['original'])//2;allowed=[h['original'],h['new']]+h.get('accepted',[])
  if data[h['offset']:h['offset']+size].hex() not in allowed:fail('Gancho da extensao desconhecido em %X'%h['offset'])
 if existing:
  slot,previous_fo,previous_size=existing;core+=cp['filesz']-previous_size
  fo=previous_fo if previous_size==cp['filesz'] else (len(data)+4095)&~4095
 else:
  slot=ph+n*stride
  if stride!=32 or slot+32>0x1000 or any(data[slot:slot+32]):fail('Sem program header livre')
  fo=(len(data)+4095)&~4095;core+=cp['filesz']
 end=max(cp['reserve_end'],verified_end,plaga_end);known_ends={end,old_end,verified_end};changes=[];heap=cp['heap']
 for hi,lo,reg in [(heap['startup_hi'],heap['startup_lo'],4),(heap['arena_hi'],heap['arena_lo'],2)]:
  w,w2=u(hi),u(lo)
  if w>>16!=(0x3c00|reg) or w2>>16!=(0x2400|(reg<<5)|reg):fail('Inicializacao da RAM desconhecida')
  value=((w&65535)<<16)+((w2&65535)-65536 if w2&32768 else w2&65535)
  if value not in known_ends and not 0x4a0000<=value<=cp['base']:fail('Limite da RAM pertence a outra modificacao')
  changes.extend([(hi,struct.pack('<I',w&0xffff0000|((end+32768)>>16))),(lo,struct.pack('<I',w2&0xffff0000|(end&65535)))])
 for o in [heap['sbrk']]+heap['symbols']:
  value=u(o)
  if value not in known_ends and not 0x4a0000<=value<=cp['base']:fail('Fim do ELF desconhecido')
  changes.append((o,struct.pack('<I',end)))
 payload=bytearray(payload);struct.pack_into('<I',payload,0x2010,core)
 def apply(result):
  out=bytearray(result)
  if len(out)<fo+cp['filesz']:out+=bytes(fo+cp['filesz']-len(out))
  if not existing:struct.pack_into('<H',out,44,n+1)
  struct.pack_into('<8I',out,slot,1,fo,cp['base'],cp['base'],cp['filesz'],cp['memsz'],7,4096);out[fo:fo+len(payload)]=payload
  for o,b in changes:out[o:o+len(b)]=b
  for h in cp['hooks']:o=h['offset'];b=bytes.fromhex(h['new']);out[o:o+len(b)]=b
  return bytes(out)
 return apply
