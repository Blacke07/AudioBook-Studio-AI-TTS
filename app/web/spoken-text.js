"use strict";
const SpokenText = {
  async confirm(request) {
    const report=await api('/api/chapter/spoken-text/preview',{method:'POST',body:request});
    if(!report.changed){toast('No spoken-text change.');return;}
    const ok=await modal('Preview spoken-text change',`<p>The manuscript and speaker stay unchanged. Audio and video plans will be checked again; only changed passages need new synthesis.</p><h3>Before</h3><div class="log">${esc(report.before || 'Stale edits will be removed')}</div><h3>After</h3><div class="log">${esc(report.after || 'Use current source text')}</div><p class="small muted">You can restore the original text from the line editor.</p>`,[{label:'Cancel',value:false},{label:'Save spoken text',value:true,primary:true}]);
    if(ok){await api('/api/chapter/spoken-text',{method:'PUT',body:{request:report.request,plan_id:report.plan_id}});toast('Spoken text saved.');route();}
  },
  async editor(volume,stem,data,index) {
    const line=data.lines[index];
    const request={volume,stem,row:index,source_hash:data.source_hash};
    const pending=modal('Edit spoken text',`<p>Edit the TTS version only. The manuscript and speaker assignments remain unchanged.</p><h3>Original manuscript line</h3><div class="log">${esc(line.text)}</div><label class="field"><span>Text to speak (maximum 10,000 characters)</span><textarea name="text" id="spoken-editor" maxlength="10000" rows="6">${esc(line.spoken_text || line.text)}</textarea></label><p class="small muted">Use punctuation to express the intended meaning: a comma for a short pause, an ellipsis for hesitation, an em dash for an interruption. Question and exclamation marks change the reading. Punctuation guides delivery; it does not guarantee emotion.</p><div class="row"><button type="button" class="btn" id="restore-spoken">Restore original</button><button type="button" class="btn" id="suggest-spoken">Suggest punctuation cleanup</button></div><p class="small muted" id="spoken-suggestion-note">Cleanup is offered for dialogue only. It tidies spacing and repeated ! or ? marks; it never guesses emotion or changes words. Review before saving.</p>`,[{label:'Cancel',value:null},{label:'Preview change',value:'form',primary:true}]);
    $('#restore-spoken').onclick=()=>{$('#spoken-editor').value=line.text;};
    $('#suggest-spoken').onclick=e=>guard(async()=>{
      const report=await api('/api/chapter/spoken-text/preview',{method:'POST',body:{...request,text:$('#spoken-editor').value}});
      if(report.suggested==null){$('#spoken-suggestion-note').textContent='This line is narration. Edit it manually; automatic cleanup applies only to dialogue.';return;}
      $('#spoken-editor').value=report.suggested;
      $('#spoken-suggestion-note').textContent='Conservative cleanup proposed. Compare it with the original above; nothing is saved until Preview and Save.';
    },e.currentTarget);
    const form=await pending;
    if(form)await this.confirm({...request,text:form.text});
  },
  bind(volume,stem,data) {
    $$('[data-edit-spoken]').forEach(button=>button.onclick=e=>guard(()=>this.editor(volume,stem,data,+button.dataset.editSpoken),e.currentTarget));
    $('[data-clear-spoken]')?.addEventListener('click',e=>guard(()=>this.confirm({volume,stem,source_hash:data.source_hash,clear_conflicts:true}),e.currentTarget));
  }
};
