import type {ReactNode} from 'react';
import katex from 'katex';
import 'katex/dist/katex.min.css';

export function formulas(text:string){
  return text.matchAll(/\\\(([\s\S]+?)\\\)|\\\[([\s\S]+?)\\\]/g);
}

export function renderMath(text:string):ReactNode{
  const parts:ReactNode[]=[];
  let start=0;
  for(const match of formulas(text)){
    const [source,inline,display]=match;
    parts.push(text.slice(start,match.index));
    try{
      const html=katex.renderToString(inline??display,{displayMode:display!==undefined,trust:false,maxExpand:100,maxSize:10,strict:'ignore'});
      parts.push(<span key={match.index} data-tex={source} className={display===undefined?undefined:'math-display'} dangerouslySetInnerHTML={{__html:html}}/>);
    }catch(error){
      if(!(error instanceof katex.ParseError))throw error;
      parts.push(source);
    }
    start=match.index+source.length;
  }
  parts.push(text.slice(start));
  return parts;
}

export function sourceText(range:Range){
  const contents=range.cloneContents();
  for(const formula of contents.querySelectorAll<HTMLElement>('[data-tex]')){
    formula.replaceWith(document.createTextNode(formula.dataset.tex!));
  }
  return contents.textContent??'';
}
