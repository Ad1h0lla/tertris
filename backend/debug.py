with open('main.py', 'r') as f:
 content = f.read()

idx = content.find('runner_result=runner_res,')
print('Context around runner_result:')
print(repr(content[idx-20:idx+80]))

# Try to find the exact pattern
target = ' )\n\n db = SessionLocal()'
found = content.find(target)
print(f'\nLooking for: {repr(target)}')
print(f'Found at index: {found}')

if found >= 0:
 print(f'Match: {repr(content[found:found+len(target)])}')
else:
 # Show what's actually there
 idx2 = content.find('db = SessionLocal()')
 if idx2 >= 0:
 print(f'Near db=SessionLocal: {repr(content[max(0,idx2-20):idx2+20])}')
