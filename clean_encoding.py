import os, re

def fix_mojibake(text):
    # Common double-encoded UTF-8 sequences
    replacements = {
        'ðŸ“¸': '📸',
        'ðŸ“ ': '📋',
        'ðŸ“': '📋',
        'ðŸ—‘ï¸ ': '🗑️',
        'ðŸ—‘': '🗑️',
        'âœ ï¸ ': '✏️',
        'âœ ': '✏️',
        'âœ…': '✅',
        'âœ•': '✕',
        'ðŸ” ': '🔍',
        'â ³': '⏳',
        'â†©ï¸ ': '↩️',
        'â†©': '↩️',
        'ðŸ›’': '🛒',
        'ðŸ’°': '💰',
        'ðŸšš': '🚚',
        'ðŸ“Š': '📊',
        'ðŸ ¾': '🏪',
        'ðŸ‘¥': '👥',
        'ðŸ”’': '🔒',
        'ðŸ–¨ï¸ ': '🖨️',
        'ðŸ–¨': '🖨️',
        'ðŸš€': '🚀',
        'â€”': '—',
        'Ã©': 'é',
        'Ã¨': 'è',
        'Ãª': 'ê',
        'Ã ': 'à',
        'Ã¢': 'â',
        'Ã®': 'î',
        'Ã´': 'ô',
        'Ã¹': 'ù',
        'Ã»': 'û',
        'Ã§': 'ç',
        'Ã€': 'À',
        'Ã‰': 'É',
        'Ãˆ': 'È',
        'Ã”': 'Ô',
        'Â': '',
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text

dirs_to_clean = [
    r"c:\Users\zinouuuuu\BILEL DESKTOP\EduShop_Cloud_Server\frontend\templates",
    r"c:\Users\zinouuuuu\BILEL DESKTOP\EduShop_v2\frontend\templates"
]

for base in dirs_to_clean:
    for root, _, files in os.walk(base):
        for file in files:
            if file.endswith(('.html', '.js', '.css', '.py')):
                fp = os.path.join(root, file)
                try:
                    with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    cleaned = fix_mojibake(content)
                    with open(fp, 'w', encoding='utf-8') as f:
                        f.write(cleaned)
                    print(f"Cleaned {file}")
                except Exception as e:
                    print(f"Error on {file}: {e}")

print("All encoding cleanup completed!")
