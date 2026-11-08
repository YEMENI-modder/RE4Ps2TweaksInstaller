"""Remove only byte-for-byte verified historical weapon-swap code."""
import struct,json,hashlib

def prepare(data,p,load,target):
 cp=p['weapon_swap'];known=[]
 for suffix,blob in [('_v15pre','_v15pre_swap.bin'),('_v15_1menu','_v15_1_swap.bin'),('_v15_2menu','_v15_2_swap.bin'),('_v15_4menu','_v15_4_swap.bin'),('_v15_5menu','_v15_5_swap.bin')]:
  q=json.loads(load(target+suffix+'.json'))['weapon_swap'];b=load(target+blob)
  # register's profile can contain a later code hash: exact blob remains ownership proof.
  if len(b)!=cp['filesz']:raise ValueError('Perfil historico incompleto.')
  known.append((b,q))
 ph=struct.unpack_from('<I',data,28)[0];stride,n=struct.unpack_from('<HH',data,42);existing=None;owned=None
 for i in range(n):
  at=ph+i*stride;t,fo,va,pa,fs,ms,flags,align=struct.unpack_from('<8I',data,at)
  if t!=1 or va!=cp['base']:continue
  if existing or (pa,fs,ms,flags,align)!=(va,cp['filesz'],cp['memsz'],7,4096) or fo+fs>len(data):raise ValueError('Segmento Weapon Swap desconhecido. Original preservado.')
  owned=next((q for b,q in known if data[fo:fo+fs]==b),None)
  if owned is None:raise ValueError('Codigo Weapon Swap desconhecido. Original preservado.')
  existing=(at,fo,fs)
 hk=cp['hook'];expected=owned['hook']['new'] if existing else hk['original']
 active=next((h for h in p['files_used']['hooks'] if h['offset']==hk['offset']),None)
 if data[hk['offset']:hk['offset']+8].hex() not in [expected]+([active['new']]+active.get('accepted',[]) if active else []):raise ValueError('Gancho da maleta desconhecido. Original preservado.')
 def apply(result):
  out=bytearray(result);count=struct.unpack_from('<H',out,44)[0]
  if existing:
   at,fo,fs=existing
   # Remove the program header without moving other segments or file offsets.
   end=ph+count*stride;out[at:end-stride]=out[at+stride:end];out[end-stride:end]=bytes(stride);count-=1;struct.pack_into('<H',out,44,count)
   other_end=max((struct.unpack_from('<I',out,ph+i*stride+4)[0]+struct.unpack_from('<I',out,ph+i*stride+16)[0] for i in range(count)),default=0)
   if fo+fs==len(out) and other_end<=fo:del out[fo:]
   else:out[fo:fo+fs]=bytes(fs)
  out[hk['offset']:hk['offset']+8]=bytes.fromhex(active['new'] if active else hk['original'])
  total=0;filesoff=None
  for i in range(count):
   t,offset,va,_,fs,_,_,_=struct.unpack_from('<8I',out,ph+i*stride)
   if t==1:total+=fs
   if t==1 and va==p['files_used']['base']:filesoff=offset
  if filesoff is not None:struct.pack_into('<I',out,filesoff+0x2010,total)
  return bytes(out)
 return apply
