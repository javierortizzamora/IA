import numpy as np, cv2, torch, json, time
from facexlib.detection import init_detection_model
torch.set_num_threads(2)
net=init_detection_model('retinaface_resnet50',half=False,device='cpu')
import subprocess
cmd=["ffmpeg","-v","error","-i","orig.mp4","-vf","crop=626:460:8:10","-f","rawvideo","-pix_fmt","bgr24","-"]
p=subprocess.Popen(cmd,stdout=subprocess.PIPE)
res={}; i=0; t0=time.time(); paso=5
while True:
    b=p.stdout.read(626*460*3)
    if len(b)<626*460*3: break
    if i%paso==0:
        if i%500==0: print(i,round(time.time()-t0),flush=True)
        img=np.frombuffer(b,np.uint8).reshape(460,626,3)
        f=512/460; up=cv2.resize(img,(int(626*f),512),interpolation=cv2.INTER_LINEAR)
        with torch.no_grad(): det=net.detect_faces(up,0.97)
        caras=[]
        for d in det:
            x1,y1,x2,y2,sc=d[:5]; lm=d[5:15].reshape(5,2)
            if np.linalg.norm(lm[0]-lm[1])<5: continue
            caras.append([round(float(v/f),1) for v in (x1,y1,x2,y2)]+[round(float(sc),3)])
        res[i]=caras
    i+=1
json.dump(res,open("caras_original.json","w")); print(i,len(res),round(time.time()-t0))
