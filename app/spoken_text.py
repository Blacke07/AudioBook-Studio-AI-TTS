"""Text spoken by TTS, separate from source text and speaker assignments."""
from copy import deepcopy
from dataclasses import replace
import re
import project
import project_package as package
import project_transfer as transfer
from voice_rules import digest

MAX_TEXT = 10000

def validate(script):
    edits = script.get('spoken_text', {})
    if not isinstance(edits, dict) or set(edits)-{'lines','conflicts'}:
        raise ValueError('Invalid spoken-text edits.')
    entries, conflicts = edits.get('lines',[]), edits.get('conflicts',[])
    if not isinstance(entries,list) or not isinstance(conflicts,list) or len(conflicts)>100000:
        raise ValueError('Invalid spoken-text edits.')
    seen=set()
    for entry in entries:
        if (not isinstance(entry,dict) or set(entry)!={'row','speaker','text_hash','source_hash','text'}
                or type(entry['row']) is not int or not 0<=entry['row']<len(script['rows']) or entry['row'] in seen):
            raise ValueError('Invalid or duplicate spoken-text edit.')
        seen.add(entry['row'])
        row=script['rows'][entry['row']]
        if (entry['speaker']!=row[0] or row[0]=='Scene break' or entry['text_hash']!=digest(row[1])
                or entry['source_hash']!=script['source_hash']):
            raise ValueError('A spoken-text edit no longer matches the source line. Review the chapter.')
        check_text(entry['text'])
    if any(not isinstance(entry,dict) for entry in conflicts):
        raise ValueError('Invalid stale spoken-text edits.')
    return edits

def check_text(text):
    if (not isinstance(text,str) or not text.strip() or len(text)>MAX_TEXT
            or any(ord(c)<32 and c not in '\n\r\t' for c in text)):
        raise ValueError('Enter 1–10,000 characters of spoken text, without control characters.')

def effective(script):
    edits=validate(script)
    if edits.get('conflicts'):
        raise ValueError('Spoken-text edits need review after the source or assignments changed. Review the chapter.')
    return {entry['row']:entry['text'] for entry in edits.get('lines',[])}

def apply_lines(lines,script):
    edits=effective(script)
    return [replace(line,text=edits.get(line.row,line.text)) for line in lines]

def reconcile(old,new):
    if not old or not old.get('spoken_text'):
        return new
    edits=deepcopy(old['spoken_text'])
    kept=[]; conflicts=edits.get('conflicts',[])
    for entry in edits.get('lines',[]):
        i=entry['row']
        if (old['source_hash']==new['source_hash'] and i<len(new['rows'])
                and entry['speaker']==new['rows'][i][0] and entry['text_hash']==digest(new['rows'][i][1])):
            kept.append(entry)
        else:
            conflicts.append(entry)
    new['spoken_text']={'lines':kept,'conflicts':conflicts}
    return new

def suggest(text):
    """Conservative punctuation cleanup; never guess a sentence's emotion or intent."""
    check_text(text)
    text=re.sub(r'([!?])\1+',r'\1',text)
    text=re.sub(r' +([,.;:!?])',r'\1',text)
    text=re.sub(r'([,;:!?])(?=[A-Za-z])',r'\1 ',text)
    return text

def plan(request):
    if not isinstance(request,dict) or set(request)-{'volume','stem','row','text','source_hash','clear_conflicts'}:
        raise ValueError('Invalid spoken-text request.')
    chapter=project.get_chapter(request['volume'],request['stem'])
    script=chapter.script()
    if (not script or script['source_hash']!=project.text_hash(chapter.text())
            or request.get('source_hash')!=script['source_hash']):
        raise ValueError('Prepare the current chapter text and refresh before editing its spoken version.')
    validate(script)
    after=deepcopy(script)
    edits=after.setdefault('spoken_text',{'lines':[],'conflicts':[]})
    edits.setdefault('lines',[])
    original=current=suggested=''
    if request.get('clear_conflicts') is True:
        edits['conflicts']=[]
    else:
        i=request.get('row')
        if type(i) is not int or not 0<=i<len(script['rows']) or script['rows'][i][0]=='Scene break':
            raise ValueError('Choose a text line, not a scene break.')
        text=request.get('text');check_text(text)
        row=script['rows'][i]; original=row[1]
        from dialogue import DIALOGUE_RE
        suggested=suggest(text) if row[0]!='Narrator' or DIALOGUE_RE.match(original) else None
        current=next((entry['text'] for entry in edits['lines'] if entry['row']==i),original)
        edits['lines']=[entry for entry in edits['lines'] if entry['row']!=i]
        if text!=original:
            edits['lines'].append({'row':i,'speaker':row[0],'text_hash':digest(original),'source_hash':script['source_hash'],'text':text})
    name=chapter.script_file.relative_to(project.ROOT).as_posix()
    writes={name:package.encoded(after)} if after!=script else {}
    report={'original':original,'before':current,'after':request.get('text',''),'suggested':suggested,'changed':bool(writes),
            'plan_id':digest([script,request]),'request':request}
    return writes,report

def save(request,plan_id):
    writes,report=plan(request)
    if report['plan_id']!=plan_id:
        raise ValueError('The chapter changed after preview. Open the text editor again.')
    if writes:
        transfer.transact(writes)
    return report
