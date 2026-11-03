import subprocess, numpy as np, cv2, sys
P="Antena 3 Noticias 28-09-1992_4K_"
grupos={"t100":[("A",P+"lanczos_t100-110s.mp4"),("B",P+"general_t100-110s.mp4"),("C",P+"x4plus_t100-110s.mp4"),("D",P+"caras_w0.85_c40-90_t100-110s.mp4")],
"cort":[("A","Cortinilla_Antena3_1992_4K_lanczos.mp4"),("B","Cortinilla_Antena3_1992_4K_general.mp4"),("C","Cortinilla_Antena3_1992_4K_x4plus.mp4")]}
idx=[25,75,125,175,225]
for g,lst in grupos.items():
    for n,f in lst:
        r=subprocess.run(["ffmpeg","-v","error","-i",f,"-vf","select='"+"+".join(f"eq(n\\,{i})" for i in idx)+"'","-vsync","0","-f","rawvideo","-pix_fmt","bgr24","-"],capture_output=True).stdout
        a=np.frombuffer(r,np.uint8).reshape(-1,2160,3840,3)
        x0,x1=(450,3390) if g=="t100" else (482,3360)
        for k,fr in zip(idx,a):
            img=cv2.resize(fr[:,x0:x1],(int((x1-x0)/2),1080),interpolation=cv2.INTER_AREA)
            cv2.imwrite(f"articulo_datos/tramos/{g}_{n}_{k:03d}.jpg",img,[cv2.IMWRITE_JPEG_QUALITY,95])
        print(g,n,len(a),x0,x1)
