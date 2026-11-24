"""Offline native build. Retains the exact command, compiler and source hash."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sysconfig,sys
R=Path(__file__).resolve().parents[1]
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,default=R/'environment/native');args=parser.parse_args()
 out=args.output_dir.resolve()
 if R not in out.parents:raise SystemExit('Build output must remain inside this project')
 out.mkdir(parents=True,exist_ok=True)
 dest=out/('_native'+sysconfig.get_config_var('EXT_SUFFIX'))
 if dest.exists():raise SystemExit('Refusing to overwrite a native binary; choose a new --output-dir')
 source=R/'src/pvldb_a/native.c'
 include=Path(sysconfig.get_path('include'))
 if not (include/'Python.h').is_file():
  include=Path('/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/include/python3.9')
 assert (include/'Python.h').is_file(), 'Matching local Python headers required'
 cmd=['xcrun','clang','-bundle','-undefined','dynamic_lookup','-O3','-std=c11','-ffp-contract=off','-fno-fast-math',
      '-I'+str(include),str(source),'-o',str(dest)]
 cp=subprocess.run(cmd,capture_output=True,text=True)
 record={'command':cmd,'returncode':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr,'python':sys.version,
  'compiler':subprocess.check_output(['xcrun','clang','--version'],text=True),
  'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'network_used':False}
 if cp.returncode==0:record['binary_sha256']=hashlib.sha256(dest.read_bytes()).hexdigest()
 # Every build log receives a new serial; existing logs are immutable.
 serial=1
 while (out/f'build_{serial:02d}.json').exists():serial+=1
 (out/f'build_{serial:02d}.json').write_text(json.dumps(record,indent=2)+'\n')
 if cp.returncode:raise SystemExit(cp.stderr)
 print(dest)
if __name__=='__main__':main()
