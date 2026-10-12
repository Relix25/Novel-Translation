import React, { useEffect, useState } from 'react';
import { Alert, Badge, Button, Checkbox, Group, Paper, SimpleGrid, Stack, Text, Textarea, TextInput, Title } from '@mantine/core';

function GlyphCard({seriesId, glyph, busy, act}) {
  const [text,setText] = useState(glyph.text ?? '');
  const [decorative,setDecorative] = useState(glyph.text === '');
  const [reason,setReason] = useState(glyph.reason || '');
  useEffect(()=>{setText(glyph.text ?? '');setDecorative(glyph.text === '');setReason(glyph.reason || '');},[glyph.text,glyph.reason]);
  const locations = glyph.occurrences.slice(0,3).map(o=>`Section ${o.number}, paragraph ${o.paragraph}`).join(' · ');
  return <Paper withBorder p="md">
    <Stack gap="sm">
      <Group justify="space-between"><img width="64" height="64" style={{objectFit:'contain',background:'white',borderRadius:6}} alt="Character as shown in the EPUB" src={`/api/glyph?series=${encodeURIComponent(seriesId)}&image_hash=${glyph.image_hash}`}/><Badge variant="light" color={glyph.text===null?'orange':'teal'}>{glyph.text===null?'To transcribe':'Transcribed'}</Badge></Group>
      <Text size="xs" c="dimmed">{locations}{glyph.occurrences.length>3?` · +${glyph.occurrences.length-3} others`:''}</Text>
      <TextInput label="Character read from the image" maxLength={20} disabled={decorative} value={text} onChange={e=>setText(e.currentTarget.value)}/>
      <Checkbox label="Decorative image: no character to add" checked={decorative} onChange={e=>setDecorative(e.currentTarget.checked)}/>
      <Textarea label="What was checked" minRows={2} value={reason} onChange={e=>setReason(e.currentTarget.value)}/>
      <Button size="sm" variant="light" loading={busy} disabled={(!decorative&&!text.trim())||!reason.trim()} onClick={()=>act({action:'glyph',series_id:seriesId,image_hash:glyph.image_hash,text:decorative?'':text,reason},'Transcription saved. Review translations whose source changed.')}>Save transcription</Button>
    </Stack>
  </Paper>;
}

export default function GlyphPanel({series,busy,act}) {
  const glyphs = series.source_glyphs || [];
  const missing = glyphs.filter(g=>g.text===null).length;
  return <Paper withBorder p="lg">
    <Group justify="space-between" mb="md"><div><Title order={3}>EPUB image characters</Title><Text size="sm" c="dimmed" mt={4}>Some books represent characters using small images. Their transcription completes the source text.</Text></div><Button size="sm" variant="default" loading={busy} onClick={()=>act({action:'scan-source-images',series_id:series.id},r=>`${r.books_checked} EPUBs checked, ${r.images_located} images located.`)}>Check archived EPUBs</Button></Group>
    {missing>0&&<Alert color="orange" mb="md">{missing} image(s) need transcription. Affected chapters cannot be generated or approved while their source text remains incomplete.</Alert>}
    {glyphs.length?<SimpleGrid cols={{base:1,sm:2,lg:3}}>{[...glyphs].sort((a,b)=>(a.text!==null)-(b.text!==null)).map(g=><GlyphCard key={`${series.id}:${g.image_hash}`} seriesId={series.id} glyph={g} busy={busy} act={act}/>)}</SimpleGrid>:<Text size="sm" c="dimmed">No image characters found. For an older import, check the archived EPUBs.</Text>}
  </Paper>;
}
