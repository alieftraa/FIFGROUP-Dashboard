import os
import re

dir_path = r'./gbp/templates/gbp'

replacements = {
    '#6C5DD3': '#0F3C8C',
    '#6c5dd3': '#0F3C8C',
    '#1FB6B6': '#00AEEF',
    '#1fb6b6': '#00AEEF',
    '#F4F3FB': '#EFF6FF',
    '#f4f3fb': '#EFF6FF',
    '#1F1B3F': '#0F172A',
    '#1f1b3f': '#0F172A',
    '#3A2FA0': '#0A235C',
    '#3a2fa0': '#0A235C',
    '#5649B8': '#0D3175',
    '#5649b8': '#0D3175',
    '108, 93, 211': '15, 60, 140',
    '108,93,211': '15,60,140',
    '31, 182, 182': '0, 174, 239',
    '31,182,182': '0,174,239',
    'bg-indigo-': 'bg-blue-',
    'border-indigo-': 'border-blue-',
    'text-indigo-': 'text-blue-',
    'hover:border-indigo-': 'hover:border-blue-'
}

count = 0
for root, dirs, files in os.walk(dir_path):
    for file in files:
        if file.endswith('.html'):
            file_path = os.path.join(root, file)
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            new_content = content
            for old, new in replacements.items():
                new_content = new_content.replace(old, new)
                
            if new_content != content:
                with open(file_path, 'w', encoding='utf-8', newline='') as f:
                    f.write(new_content)
                count += 1
                print(f'Updated {file_path}')

print(f'Total updated files: {count}')
