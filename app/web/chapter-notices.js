/* Optional chapter information is compact; blocking errors remain in the chapter body. */
const ChapterNotices = {
  html(data) {
    const video=data.chapter.video, proposed=data.lines.filter(line=>line.emotion_source==='ai').length;
    const context=data.lines.filter(line=>line.basis==='context').length;
    const pacing=data.lines.filter(line=>line.flagged).length;
    const analyzed=!data.manual_draft && Boolean(data.report || data.lines.length);
    const unassigned=data.lines.filter(line=>line.speaker==='Unassigned').length;
    const blockers=data.blockers||[];
    const missing=(data.missing_takes||[]).map(pair=>{
      const [role,key]=pair.split('|'),label=(data.emotions||[]).find(e=>e.key===key)?.label||key;
      return `${esc(label.toLowerCase())} for ${esc(role)}`;
    });
    const note=(key,label,symbol,count,body,state=key==='report'?'report':count?'warning':'complete')=>`<details class="chapter-notice ${state}" data-chapter-notice="${key}"><summary class="btn small" aria-label="${esc(label)}${count==null||key==='report'?'':count?` · ${count} to review`:' · No pending items'}" title="${esc(label)}">${icon(state==='complete'?'check':symbol)}${key==='report'?'':`<span>${esc(label)}</span>${count==null?'':`<span class="notice-count">${count}</span>`}`}</summary><div class="chapter-notice-panel"><div class="row between"><h3>${esc(label)}</h3><button type="button" class="btn small" data-notice-close>Close</button></div>${body}</div></details>`;
    const go=(key,label)=>`<button type="button" class="btn status-warn" data-review-go="${key}">${label}</button>`;
    const files=video.url?`<a class="btn" href="${esc(video.url)}" target="_blank" rel="noopener">${icon('play')} Open video</a><button class="btn" id="show-video">${icon('folder')} Show in folder</button>`:'';
    const notices=(data.manual_draft||data.chapter.analysis_problem?note('manual','Manual editor','book',null,`<p>Assign speakers beside the text or split a line. Gemma is not required; the original chapter file stays unchanged.</p><button type="button" class="btn small" id="save-manual">${data.manual_draft?'Use manual assignments':'Keep these assignments'}</button>`,'warning'):'')
      +(data.lines.length?note('speakers','Unassigned','flag',unassigned,unassigned?`<p>${unassigned} ${unassigned===1?'line needs':'lines need'} a speaker.</p><button type="button" class="btn small status-warn" data-unassigned>Go to unassigned lines</button>`:'<p>All displayed lines have a speaker. Character approvals are checked separately.</p>',unassigned?'warning':analyzed?'complete':'neutral'):'')
      +(data.lines.length?note('characters','Characters','flag',blockers.length,blockers.length?`<p>${blockers.length} ${blockers.length===1?'character needs':'characters need'} approval.</p><div class="review-character-list">${blockers.map(b=>{
        const first=data.lines.findIndex(line=>line.speaker===b.name);
        return `<div class="row"><button type="button" class="btn small status-warn" data-review-character="${esc(b.name)}">Review ${esc(b.label)}</button>${first>=0?`<button type="button" class="btn small" data-queue-go="${first}">Go to line</button>`:''}</div>`;
      }).join('')}</div>`:'<p>No character approvals pending in this chapter.</p>',blockers.length?'warning':analyzed?'complete':'neutral'):'')
      +(analyzed||missing.length?note('missing','Emotion takes','flag',missing.length,missing.length?`<p><b>Some emotions use the neutral take.</b> No approved take: ${missing.join(', ')}. A fixed voice takes no instructions, so these lines keep the neutral delivery.</p>${go('missing','Go to affected line')}<a href="#/characters">Approve emotion takes in Characters</a>`:'<p>No missing emotion takes for this chapter.</p>'):'')
      +(analyzed||proposed?note('proposed','Emotions','wand',proposed,proposed?`<p><b>${proposed} ${proposed===1?'emotion was':'emotions were'} proposed by Gemma.</b> Choose another emotion or Keep beside each affected line. Your choices are kept when you analyze again.</p>${go('proposed','Go to emotion proposal')}`:'<p>No emotion proposals waiting for your decision.</p>'):'')
      +(analyzed?note('context','Context','flag',context,context?`<p>${context} speaker ${context===1?'assignment was':'assignments were'} inferred from context. These are separate from Unassigned lines.</p>${go('context','Go to context assignment')}`:'<p>No context-inferred speaker assignments to check.</p>'):'')
      +(analyzed?note('pacing','Pacing','flag',pacing,pacing?`<p>${pacing} ${pacing===1?'line has':'lines have'} unusual pacing. Listen before choosing another take.</p>${go('pacing','Go to pacing warning')}`:'<p>No unusual pacing was flagged.</p>'):'')
      +(data.report?note('report','Analysis report','info',0,`<div class="log">${esc(data.report)}</div>`):'');
    return files||notices?`<div class="chapter-notices row" aria-label="Chapter files and information">${files}${notices}</div>`:'';
  },
  bind(root){
    const bar=root.querySelector('.chapter-notices');if(!bar)return;
    const notes=[...bar.querySelectorAll('[data-chapter-notice]')];
    bar.onclick=event=>{
      const item=event.target.closest('[data-chapter-notice]');
      if(!item)return;
      if(event.target.closest('[data-queue-go], [data-unassigned], [data-review-go], [data-review-character], #save-manual'))item.open=false;
      else if(event.target.closest('[data-notice-close]')){item.open=false;item.querySelector('summary').focus();}
      else if(event.target.closest('summary'))notes.forEach(note=>{if(note!==item)note.open=false;});
    };
    bar.onkeydown=event=>{
      if(event.key!=='Escape')return;
      const item=notes.find(note=>note.open);if(!item)return;
      event.stopPropagation();item.open=false;item.querySelector('summary').focus();
    };
  },
};
