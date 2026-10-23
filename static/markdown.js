/* A deliberately small Markdown renderer. Provider text never becomes raw HTML. */
(function(root){
  const escape = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function inline(source, depth=0){
    if(depth>8)return escape(source);
    const pattern=/`([^`\n]+)`|\[([^\]\n]+)\]\(([^\s)]+)\)|\*\*([^*\n]+)\*\*|__([^_\n]+)__|\*([^*\n]+)\*|~~([^~\n]+)~~/g;
    let html='',offset=0;
    for(const match of source.matchAll(pattern)){
      html+=escape(source.slice(offset,match.index));
      if(match[1]!==undefined)html+='<code>'+escape(match[1])+'</code>';
      else if(match[2]!==undefined){
        const href=match[3];
        html+=/^https?:\/\//i.test(href)?'<a href="'+escape(href)+'" target="_blank" rel="noopener noreferrer">'+inline(match[2],depth+1)+'</a>':inline(match[2],depth+1);
      }else if(match[4]!==undefined||match[5]!==undefined)html+='<strong>'+inline(match[4]??match[5],depth+1)+'</strong>';
      else if(match[6]!==undefined)html+='<em>'+inline(match[6],depth+1)+'</em>';
      else html+='<del>'+inline(match[7],depth+1)+'</del>';
      offset=match.index+match[0].length;
    }
    return html+escape(source.slice(offset));
  }
  const listItem=line=>line.match(/^(\s*)([-+*]|\d+[.)])\s+(.+)$/);
  const tableCells=line=>line.trim().replace(/^\|/,'').replace(/\|$/,'').split('|').map(cell=>cell.trim());
  const tableRule=line=>/^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  function renderMarkdown(value,depth=0){
    if(depth>12)return '<p>'+escape(value)+'</p>';
    const lines=String(value??'').replace(/\r\n?/g,'\n').split('\n');
    let i=0,html='';
    const startsBlock=index=>/^(?:#{1,6}\s|\s*```|>\s?|\s*(?:[-+*]|\d+[.)])\s+|\s*(?:---+|\*\*\*+)\s*$)/.test(lines[index]||'') || (lines[index]?.includes('|')&&tableRule(lines[index+1]||''));
    while(i<lines.length){
      const line=lines[i];
      if(!line.trim()){i++;continue;}
      const fence=line.match(/^\s*```([\w+-]*)\s*$/);
      if(fence){
        const body=[];i++;
        while(i<lines.length&&!/^\s*```\s*$/.test(lines[i]))body.push(lines[i++]);
        if(i<lines.length)i++;
        html+='<div class="report-code">'+(fence[1]?'<div class="code-language">'+escape(fence[1])+'</div>':'')+'<pre><code>'+escape(body.join('\n'))+'</code></pre></div>';continue;
      }
      const heading=line.match(/^(#{1,6})\s+(.+?)\s*#*$/);
      if(heading){const level=Math.min(heading[1].length+1,6);html+='<h'+level+'>'+inline(heading[2])+'</h'+level+'>';i++;continue;}
      if(/^\s*(?:---+|\*\*\*+)\s*$/.test(line)){html+='<hr>';i++;continue;}
      if(/^>/.test(line)){
        const body=[];while(i<lines.length&&/^>/.test(lines[i]))body.push(lines[i++].replace(/^>\s?/,''));
        html+='<blockquote>'+renderMarkdown(body.join('\n'),depth+1)+'</blockquote>';continue;
      }
      if(line.includes('|')&&tableRule(lines[i+1]||'')){
        const headers=tableCells(line);i+=2;
        html+='<div class="report-table"><table><thead><tr>'+headers.map(c=>'<th>'+inline(c)+'</th>').join('')+'</tr></thead><tbody>';
        while(i<lines.length&&lines[i].includes('|')&&lines[i].trim()){
          const cells=tableCells(lines[i++]);html+='<tr>'+headers.map((_,n)=>'<td>'+inline(cells[n]||'')+'</td>').join('')+'</tr>';
        }
        html+='</tbody></table></div>';continue;
      }
      const first=listItem(line);
      if(first){
        const indent=first[1].length,ordered=/\d/.test(first[2]),tag=ordered?'ol':'ul';
        html+='<'+tag+(ordered?' start="'+parseInt(first[2],10)+'"':'')+'>';
        while(i<lines.length){
          const item=listItem(lines[i]);
          if(!item||item[1].length!==indent||/\d/.test(item[2])!==ordered)break;
          html+='<li>'+inline(item[3]);i++;
          const nested=[];
          while(i<lines.length&&lines[i].trim()&&/^\s+/.test(lines[i])&&lines[i].match(/^\s*/)[0].length>indent){
            nested.push(lines[i++].slice(indent+2));
          }
          if(nested.length)html+=renderMarkdown(nested.join('\n'),depth+1);
          html+='</li>';
        }
        html+='</'+tag+'>';continue;
      }
      const paragraph=[line.trim()];i++;
      while(i<lines.length&&lines[i].trim()&&!startsBlock(i))paragraph.push(lines[i++].trim());
      html+='<p>'+inline(paragraph.join(' '))+'</p>';
    }
    return html;
  }
  if(typeof module!=='undefined'&&module.exports)module.exports=renderMarkdown;
  else root.renderMarkdown=renderMarkdown;
})(typeof globalThis!=='undefined'?globalThis:this);
