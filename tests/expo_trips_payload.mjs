// Test-only bridge: run the actual TS form helper against synthetic Flask DTOs.
import {readFileSync} from 'node:fs';
import {newDraft,editDraft,previewPayload} from '../frontend/src/lib/trips.ts';
const input=JSON.parse(readFileSync(0,'utf8'));
const draft=input.journey?editDraft(input.journey):newDraft(input.people,'2026-10-01');
if(!input.journey){draft.plan.title='合成苏州旅行';draft.plan.destinations[0].city='苏州';draft.plan.end='2026-10-03';draft.plan.destinations[0].departure='2026-10-03';draft.budget='1234.29';}
if(input.title)draft.plan.title=input.title;
process.stdout.write(JSON.stringify(previewPayload(draft,input.people)));
