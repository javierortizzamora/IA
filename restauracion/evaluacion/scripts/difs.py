import sys,subprocess,numpy as np
ruta,ini,n=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]); W,H=3840,2160
cmd=["ffmpeg","-v","error","-ss",f"{ini/25:.4f}","-i",ruta,"-frames:v",str(n+1),"-f","rawvideo","-pix_fmt","rgb24","-"]
p=subprocess.Popen(cmd,stdout=subprocess.PIPE,bufsize=W*H*3)
def leer():
    b=p.stdout.read(W*H*3); return None if len(b)<W*H*3 else np.frombuffer(b,np.uint8).reshape(H,W,3)
x0,x1=450,3390
prev=leer(); out=[]; k=ini
while True:
    cur=leer()
    if cur is None: break
    d=np.abs(cur[:,x0:x1].astype(np.int16)-prev[:,x0:x1]).mean()/255.
    k+=1; out.append(f"{k},{d:.5f}"); prev=cur
open(sys.argv[4],"a").write("\n".join(out)+"\n"); print(ini,len(out))
