#!/usr/bin/env python3
"""Local read-only binary/environment audit; output must be a fresh path."""
import ctypes
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/e_stages/E03/E03_2026-11-18_03'
assert sys.version_info[:3] == (3, 9, 6) and platform.machine() == 'arm64'
assert not (OUT / 'runtime_binding.json').exists()
def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class MethodDef(ctypes.Structure):
    _fields_ = [('name', ctypes.c_char_p), ('meth', ctypes.c_void_p),
                ('flags', ctypes.c_int), ('doc', ctypes.c_char_p)]
class Head(ctypes.Structure):
    _fields_ = [('refcnt', ctypes.c_ssize_t), ('type', ctypes.c_void_p),
                ('ml', ctypes.POINTER(MethodDef))]
class DlInfo(ctypes.Structure):
    _fields_ = [('fname', ctypes.c_char_p), ('fbase', ctypes.c_void_p),
                ('sname', ctypes.c_char_p), ('saddr', ctypes.c_void_p)]

probe_path = OUT / 'fp_environment_probe.dylib'
probe = ctypes.CDLL(str(probe_path))
for name in ['c1_read_fpcr', 'c1_number_offset', 'c1_multiply_offset']:
    getattr(probe, name).restype = ctypes.c_uint64
assert probe.c1_read_fpcr() == 0
assert probe.c1_rounding() == probe.c1_nearest_constant()
lib = ctypes.CDLL(None)
lib.dladdr.argtypes = [ctypes.c_void_p, ctypes.POINTER(DlInfo)]
lib.dladdr.restype = ctypes.c_int
ml = Head.from_address(id(math.fsum)).ml.contents
assert ml.name == b'fsum' and ml.flags == 8
number = ctypes.c_void_p.from_address(id(float) + probe.c1_number_offset()).value
mul = ctypes.c_void_p.from_address(number + probe.c1_multiply_offset()).value

result = {'python': sys.version, 'executable': str(Path(sys.executable).resolve()),
          'executable_sha256': sha(sys.executable), 'platform': platform.platform(),
          'float_info': {k:getattr(sys.float_info,k) for k in
                         ['radix','mant_dig','rounds','min_exp','max_exp']},
          'fpcr': probe.c1_read_fpcr(), 'fegetround': probe.c1_rounding(),
          'FE_TONEAREST': probe.c1_nearest_constant(),
          'probe_sha256': sha(probe_path),
          'header_offsets': {'tp_as_number':probe.c1_number_offset(),
                             'nb_multiply':probe.c1_multiply_offset()},
          'functions': {}, 'network_used':False,
          'limits':'Manual binary-to-algorithm audit plus analytic proof; not formal machine-code verification.'}
for name, address, size in [('fsum', ml.meth, 0x3410-0x2f28), ('float_multiply',mul,0x180)]:
    info = DlInfo(); assert lib.dladdr(address,ctypes.byref(info))
    origin = Path(info.fname.decode())
    entry = address - info.fbase
    copied = OUT / (name+'_runtime_binary')
    shutil.copy2(origin,copied)
    thin = OUT / (name+'_arm64_binary')
    subprocess.run(['xcrun','lipo',str(copied),'-thin','arm64','-output',str(thin)],check=True)
    disk = thin.read_bytes()[entry:entry+size]
    memory = ctypes.string_at(address,size)
    assert disk == memory, 'Loaded instructions differ from captured arm64 file'
    full = subprocess.check_output(['xcrun','llvm-objdump','--macho','--arch=arm64',
                                   '--disassemble',str(thin)],text=True)
    lines = []
    for line in full.splitlines():
        match = re.match(r'\s*([0-9a-f]+):',line)
        if match and entry <= int(match[1],16) < entry+size: lines.append(line)
    (OUT / (name+'_disassembly.txt')).write_text('\n'.join(lines)+'\n')
    (OUT / (name+'_instructions.bin')).write_bytes(memory)
    result['functions'][name] = {'origin':str(origin),'origin_sha256':sha(origin),
        'copy':str(copied.relative_to(ROOT)),'arm64_sha256':sha(thin),
        'entry_relative_to_image':hex(entry),'window_bytes':size,
        'instruction_sha256':hashlib.sha256(memory).hexdigest(),
        'memory_equals_file':True,'disassembly_lines':len(lines)}
assert probe.c1_read_fpcr() == 0
result['fpcr_after']=probe.c1_read_fpcr()
(OUT/'runtime_binding.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'runtime_capture':'pass','fpcr':result['fpcr'],
                  'entries':{k:v['entry_relative_to_image'] for k,v in result['functions'].items()}}))
