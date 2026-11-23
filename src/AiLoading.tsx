import type {ReactNode} from 'react';

export function AiLoading({active,variant,children}:{
  active:boolean,variant:'dots'|'orbit'|'wave',children:ReactNode
}){
  return <div className="ai-loading" role="status">{active&&<>
    <span className={'ai-loading-icon '+variant} aria-hidden="true"><i/><i/><i/></span>
    {children}
  </>}</div>
}
