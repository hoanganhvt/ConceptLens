import {tr, language} from './language';
export type Topic={id:string,title:string,goal:string};
export type Road={id:string,title:string,goal:string,chapters:{title:string,topics:Topic[]}[]};
export type Visual={section:number,title:string,instruction:string,explanation:string,mode:'motion'|'interactive',html:string,css:string,js:string};
export type Lesson={version:string,intro:string,sections:{title:string,text:string}[],illustrations:Visual[],quiz:{kind:'number'|'choice',prompt:string,choices:string[]}[]};
export type Anchor={id:string,version:string,block:string,start:number,end:number,quote:string,snapshot:Record<string,number>|null};
export type Msg={role:string,text:string,sources?:{title:string,url:string,start:number,end:number}[],traces?:unknown[]};
export type Progress=Record<string,{answer:string,correct:boolean,explanation:string,attempt_id?:string,can_remember?:boolean}[]>;
export type Bundle={doc:Lesson|null,progress:Progress,notes:Anchor[],main:Msg[],scroll:number};
export type Sim={params:{acceleration:number,velocity:number,duration:number},points:{s:number,v:number,t:number}[],marks?:{s:number,t:number}[],index:number};
export async function api<T>(path:string,body?:unknown,method=body===undefined?'GET':'POST'):Promise<T>{
  const headers=new Headers({'X-Study-Language':language});
  if(body!==undefined)headers.set('Content-Type','application/json');
  const response=await fetch('/api/'+path,{method,headers,body:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok) throw Error(typeof data.detail==='string'?data.detail:tr("Dữ liệu không hợp lệ. Hãy kiểm tra rồi thử lại.", "Invalid input. Check your entries and try again."));
  return data;
}
export const fmt=(n:number)=>n.toLocaleString(language,{maximumFractionDigits:2});

