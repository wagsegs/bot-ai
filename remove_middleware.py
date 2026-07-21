from pathlib import Path

base = Path(__file__).resolve().parent
chat_file = base / 'cogs' / 'ai_chat.py'
text = chat_file.read_text(encoding='utf-8')
start = text.find('class AIRequestMiddleware:')
end = text.rfind('class AIChatCog(commands.Cog):')
if start == -1 or end == -1:
    raise SystemExit('Boundaries not found: start=%s end=%s' % (start, end))
new_text = text[:start] + text[end:]
chat_file.write_text(new_text, encoding='utf-8')
print('removed middleware class')
