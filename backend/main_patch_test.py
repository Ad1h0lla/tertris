import sys
sys.path.insert(0, 'E:/tetris-recovery/recovered-source')
sys.path.insert(0, '.')

import importlib.util
spec = importlib.util.spec_from_file_location('tetris_main', 'main.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

print('\nPatched app routes:')
from fastapi.routing import APIRoute
for route in mod.app.routes:
    if isinstance(route, APIRoute) and route.path in ['/intake', '/intake/reply']:
        print(f'  {list(route.methods)} {route.path}')
        print(f'    endpoint: {route.endpoint.__name__}')
        print(f'    body_field: {route.body_field}')
        dep = route.dependant
        if dep:
            bp = [p.name for p in dep.body_params]
            print(f'    dependant body_params: {bp}')
        else:
            print('    no dependant')
