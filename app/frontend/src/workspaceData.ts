import type { Project, WorkspaceDocument } from './types';
export interface FileFilters {search:string;projectId:string;companyId:string;status:string;version:string;kind:string}
export function filterFiles(documents:WorkspaceDocument[],filters:FileFilters){
 const query=filters.search.trim().toLocaleLowerCase();
 return documents.filter(doc=>(!filters.projectId||(filters.projectId==='unassigned'?!doc.project_id:doc.project_id===filters.projectId))&&(!filters.companyId||doc.company_id===filters.companyId)&&(!filters.status||doc.status===filters.status)&&(!filters.kind||doc.document_kind===filters.kind)&&(!filters.version||(filters.version==='current'?(doc.is_current!==false||doc.replacement_pending||isFailedReplacement(doc)):doc.is_current===false&&!doc.replacement_pending&&!isFailedReplacement(doc)))&&(!query||[doc.name,doc.company_name,doc.project_name,doc.review_name,doc.document_kind].filter(Boolean).join(' ').toLocaleLowerCase().includes(query))).sort((a,b)=>(b.uploaded_at??'').localeCompare(a.uploaded_at??'')||a.name.localeCompare(b.name)||a.id.localeCompare(b.id));
}
export function projectCompanyIds(project?:Project){return new Set((project?.parties??[]).map(p=>p.company_id));}
type VersionMetadata={version_number?:number;is_current?:boolean;replacement_pending?:boolean;status?:string;previous_document_id?:string;error?:string};
export function isFailedReplacement(doc:VersionMetadata){return doc.is_current===false&&doc.status==='failed'&&!!(doc.previous_document_id||doc.error);}
export function documentVersionLabel(doc:VersionMetadata){return `v${doc.version_number??1} · ${isFailedReplacement(doc)?'Replacement failed':doc.replacement_pending?'Awaiting extraction':doc.is_current===false?'Superseded':'Current'}`;}
