import type {User} from 'firebase/auth';
let account:User|null=null;
export const accountKey=()=>account?.uid||'local';
let analysis='example';
export const analysisKey=()=>analysis;
export function setAnalysis(id:string){if(id!==analysis)tasks.clear();analysis=id;}
export function setAccount(user:User|null){if(user?.uid!==account?.uid)tasks.clear();account=user;}
import type {Job} from './types';
export async function request<T>(path:string,body?:unknown,method=body?'POST':'GET',signal?:AbortSignal,scope=analysis):Promise<T>{
  const uid=accountKey();
  const token=account?await account.getIdToken():null;
  const headers:Record<string,string>={'X-Analysis-ID':scope};
  if(body)headers['Content-Type']='application/json';
  if(token)headers.Authorization=`Bearer ${token}`;
  const response=await fetch(`/api${path}`,{method,headers,body:body?JSON.stringify(body):undefined,signal});
  if(uid!==accountKey()||(!path.startsWith('/analyses')&&scope!==analysis))throw new DOMException('Workspace changed','AbortError');
  const data=await response.json();
  if(!response.ok)throw new Error(data.error||'The request could not be completed.');
  return data;
}
export async function waitJob<T>(job:Job<T>,signal?:AbortSignal,scope=analysis):Promise<T>{
  let current=job;
  while(current.status==='running'){
    await new Promise<void>((resolve,reject)=>{const timer=window.setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve();},700);const abort=()=>{window.clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();});
    current=await request<Job<T>>(`/jobs/${job.job_id}`,undefined,'GET',signal,scope);
  }
  if(current.status==='failed')throw new Error(current.error||'The request failed. Please retry.');
  return current.result as T;
}
const tasks=new Map<string,Promise<unknown>>();
export async function task<T>(path:string,body:Record<string,unknown>,signal?:AbortSignal):Promise<T>{
  const scope=analysis;
  const key=accountKey()+scope+path+JSON.stringify(body);
  if(!tasks.has(key)){
    const promise=request<Job<T>>(path,{...body,request_id:crypto.randomUUID()},'POST',undefined,scope).then(job=>waitJob(job,undefined,scope));
    tasks.set(key,promise);
    promise.catch(()=>tasks.delete(key));
  }
  const pending=tasks.get(key) as Promise<T>;
  if(!signal)return pending;
  return new Promise<T>((resolve,reject)=>{
    const abort=()=>reject(new DOMException('Aborted','AbortError'));
    signal.addEventListener('abort',abort,{once:true});
    if(signal.aborted)abort();
    pending.then(value=>{signal.removeEventListener('abort',abort);if(!signal.aborted)resolve(value);},error=>{signal.removeEventListener('abort',abort);reject(error);});
  });
}
