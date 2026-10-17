import {test} from 'node:test';
import assert from 'node:assert/strict';
import {documentVersionLabel,filterFiles} from '../src/workspaceData.ts';
import type {WorkspaceDocument} from '../src/types.ts';
const make=(id:string,overrides:Partial<WorkspaceDocument>={}):WorkspaceDocument=>({id,name:`${id}.pdf`,sha256:id,status:'processed',page_count:1,review_id:'review',review_name:'October review',...overrides});
const base={search:'',projectId:'',companyId:'',status:'',version:'current',kind:''};
test('current view retains incoming and failed replacements while hiding superseded evidence',()=>{
 const docs=[make('old',{is_current:false}),make('current',{is_current:true}),make('incoming',{is_current:false,replacement_pending:true,status:'pending'}),make('failed',{is_current:false,status:'failed',previous_document_id:'current',error:'Unreadable PDF'})];
 assert.deepEqual(filterFiles(docs,base).map(d=>d.id),['current','failed','incoming']);
 assert.deepEqual(filterFiles(docs,{...base,version:'superseded'}).map(d=>d.id),['old']);
 assert.equal(filterFiles(docs,{...base,version:''}).length,4);
});
test('failed replacement is never described as superseded or current',()=>{
 assert.equal(documentVersionLabel({version_number:2,is_current:false,status:'failed',previous_document_id:'old'}),'v2 · Replacement failed');
 assert.equal(documentVersionLabel({version_number:2,is_current:false,replacement_pending:true}),'v2 · Awaiting extraction');
 assert.equal(documentVersionLabel({version_number:1,is_current:false,status:'processed'}),'v1 · Superseded');
 assert.equal(documentVersionLabel({}),'v1 · Current');
});
test('project, company, type and text filters combine without crossing project boundaries',()=>{
 const docs=[make('match',{project_id:'a',company_id:'vendor',document_kind:'policy',company_name:'Nimbus'}),make('other-project',{project_id:'b',company_id:'vendor',document_kind:'policy',company_name:'Nimbus'}),make('other-company',{project_id:'a',company_id:'buyer',document_kind:'policy',company_name:'Aster'})];
 assert.deepEqual(filterFiles(docs,{...base,projectId:'a',companyId:'vendor',kind:'policy',search:' NIMBUS '}).map(d=>d.id),['match']);
});
test('unassigned files are separate from project files and sorting does not mutate source',()=>{
 const docs=[make('earlier',{uploaded_at:'2026-10-01'}),make('newer',{uploaded_at:'2026-10-02'}),make('project',{project_id:'a'})];
 assert.deepEqual(filterFiles(docs,{...base,projectId:'unassigned'}).map(d=>d.id),['newer','earlier']);
 assert.deepEqual(docs.map(d=>d.id),['earlier','newer','project']);
});
