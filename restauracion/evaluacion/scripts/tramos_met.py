import glob,os,csv,torch,pyiqa,warnings;warnings.filterwarnings("ignore");torch.set_num_threads(2)
ms={n:pyiqa.create_metric(n,device="cpu") for n in ["niqe","musiq","clipiqa"]}
with open("res_tramos.csv","w",buffering=1) as fo:
    w=csv.writer(fo);w.writerow(["img"]+list(ms))
    for p in sorted(glob.glob("tramos/*.jpg")):
        x=pyiqa.utils.imread2tensor(p).unsqueeze(0)
        with torch.no_grad(): w.writerow([os.path.basename(p)[:-4]]+[round(float(m(x)),4) for m in ms.values()])
print("ok")
