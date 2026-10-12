import React,{useEffect,useState} from 'react';
import {Alert,Badge,Button,Group,Paper,Progress,SimpleGrid,Stack,Text,Title} from '@mantine/core';

function windowLabel(n){return n==null?'Unspecified window':n%1440===0?`${n/1440} day${n===1440?'':'s'}`:n%60===0?`${n/60} h`:`${n} min`;}
export default function QuotaPanel({data,connected,onRefresh,compact=false}){
 const [now,setNow]=useState(Date.now());
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),30000);return()=>clearInterval(timer);},[]);
 const windows=(data?.buckets||[]).flatMap(b=>b.windows.map(w=>({...w,bucket:b.name,id:`${b.id}-${w.key}`})));
 return <Paper withBorder p={compact?'md':'lg'}><Stack gap="sm"><Group justify="space-between"><div><Title order={compact?4:3}>Codex account quota</Title>{!compact&&<Text c="dimmed" size="sm">Measured across the account · separate from chapter tokens</Text>}</div><Button size="xs" variant="default" disabled={!connected||data?.refreshing} loading={data?.refreshing} onClick={onRefresh}>Refresh</Button></Group>
 {windows.length?<SimpleGrid cols={{base:1,sm:2}}>{windows.map(w=>{const stale=w.stale||now-Date.parse(w.observed_at)>120000||(w.resets_at&&w.resets_at*1000<=now);return <div key={w.id}><Group justify="space-between" mb={6}><Text size="sm">{w.bucket} · {windowLabel(w.duration_minutes)}</Text><Badge variant="light" color={stale?'gray':w.remaining_percent<20?'orange':'teal'}>{w.remaining_percent}% remaining{stale?' · stale reading':''}</Badge></Group><Progress value={w.remaining_percent} color={stale?'gray':w.remaining_percent<20?'orange':'teal'}/><Text size="xs" c="dimmed" mt={5}>Resets: {w.resets_at?new Date(w.resets_at*1000).toLocaleString('en-GB'):'not reported'}</Text></div>;})}</SimpleGrid>:<Text size="sm" c="dimmed">{connected?'Quota is not available yet. Refresh to query Codex.':'Connect Codex to display the included account quota.'}</Text>}
 {data?.ordinary_usage_allowed===false&&<Alert color="orange">Codex reports that included usage is currently unavailable.</Alert>}
 {data?.error&&<Text size="xs" c="orange">{data.error}</Text>}
 {data?.updated_at&&<Text size="xs" c="dimmed">Last reading: {new Date(data.updated_at).toLocaleString('en-GB')}</Text>}
 {!compact&&<Text size="xs" c="dimmed">{data?.note||'This quota is shared with your other Codex activity. Tokens and credits cannot be reliably converted to a quota percentage per chapter.'}</Text>}
 </Stack></Paper>;
}
