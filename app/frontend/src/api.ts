import type { Review } from './types';
let token: (()=>Promise<string>) | undefined;
let sessionInitialization:Promise<unknown>|undefined;
export function initializeSession(){return sessionInitialization??=(startSession());}
async function startSession() {
  const response=await fetch('/api/session',{credentials:'same-origin'});
  if(!response.ok)throw new Error(`Session service returned ${response.status}. Reload to try again.`);
  const session=await response.json();
  const configured=import.meta.env.VITE_FIREBASE_CONFIG;
  const config=session.firebase_config || (configured ? JSON.parse(configured):null);
  if(config && (session.auth_mode==='firebase'||configured)) {
    const [{initializeApp},{getAuth,signInAnonymously,browserLocalPersistence,setPersistence}]=await Promise.all([import('firebase/app'),import('firebase/auth')]);
    const auth=getAuth(initializeApp(config));
    await setPersistence(auth,browserLocalPersistence);
    await auth.authStateReady();
    if(!auth.currentUser) await signInAnonymously(auth);
    token=async()=>{if(!auth.currentUser)throw new Error('Your session has ended. Reload to sign in again.');return auth.currentUser.getIdToken();};
  }
  return session;
}
export async function api<T>(path:string,options:RequestInit={}):Promise<T>{
  const response=await request(path,options);
  return response.status===204 ? undefined as T:response.json();
}
export async function request(path:string,options:RequestInit={}){
  const headers=new Headers(options.headers);
  if(options.body && !(options.body instanceof FormData))headers.set('Content-Type','application/json');
  if(token)headers.set('Authorization',`Bearer ${await token()}`);
  const response=await fetch(path,{...options,headers,credentials:'same-origin'});
  if(!response.ok){const payload=await response.json().catch(()=>({}));const detail=payload.detail??payload.error??payload.message;throw new Error(typeof detail==='string'?detail:detail?JSON.stringify(detail):`Request failed (${response.status}). Please try again.`)}
  return response;
}
export async function download(path:string,name:string,open=false,page?:number){
  // Reserve the new tab synchronously so browsers do not block an authenticated PDF.
  const tab=open?window.open('about:blank','_blank'):null;
  try{
    const response=await request(path); const url=URL.createObjectURL(await response.blob());
    if(open && tab){tab.opener=null;tab.location.href=`${url}${page?`#page=${page}`:''}`;}else{const link=document.createElement('a');link.href=url;link.download=name;link.click()}
    window.setTimeout(()=>URL.revokeObjectURL(url),120000);
  }catch(error){tab?.close();throw error;}
}
export const getReview=(id:string)=>api<Review>(id==='sample'?'/api/sample':`/api/reviews/${encodeURIComponent(id)}`);
