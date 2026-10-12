import React, { useEffect, useState } from 'react';
import { Alert, Badge, Button, Checkbox, Group, Paper, SimpleGrid, Stack, Text, Textarea, TextInput, Title } from '@mantine/core';

function GlyphCard({seriesId, glyph, busy, act}) {
  const [text,setText] = useState(glyph.text ?? '');
  const [decorative,setDecorative] = useState(glyph.text === '');
  const [reason,setReason] = useState(glyph.reason || '');
  useEffect(()=>{setText(glyph.text ?? '');setDecorative(glyph.text === '');setReason(glyph.reason || '');},[glyph.text,glyph.reason]);
  const locations = glyph.occurrences.slice(0,3).map(o=>`Section ${o.number}, paragraphe ${o.paragraph}`).join(' · ');
  return <Paper withBorder p="md">
    <Stack gap="sm">
      <Group justify="space-between"><img width="64" height="64" style={{objectFit:'contain',background:'white',borderRadius:6}} alt="Caractère tel qu’il apparaît dans l’EPUB" src={`/api/glyph?series=${encodeURIComponent(seriesId)}&image_hash=${glyph.image_hash}`}/><Badge variant="light" color={glyph.text===null?'orange':'teal'}>{glyph.text===null?'À transcrire':'Transcrit'}</Badge></Group>
      <Text size="xs" c="dimmed">{locations}{glyph.occurrences.length>3?` · +${glyph.occurrences.length-3} autres`:''}</Text>
      <TextInput label="Caractère lu dans l’image" maxLength={20} disabled={decorative} value={text} onChange={e=>setText(e.currentTarget.value)}/>
      <Checkbox label="Image décorative : aucun caractère à ajouter" checked={decorative} onChange={e=>setDecorative(e.currentTarget.checked)}/>
      <Textarea label="Ce qui a été vérifié" minRows={2} value={reason} onChange={e=>setReason(e.currentTarget.value)}/>
      <Button size="sm" variant="light" loading={busy} disabled={(!decorative&&!text.trim())||!reason.trim()} onClick={()=>act({action:'glyph',series_id:seriesId,image_hash:glyph.image_hash,text:decorative?'':text,reason},'Transcription enregistrée. Relire les traductions dont la source a changé.')}>Enregistrer la transcription</Button>
    </Stack>
  </Paper>;
}

export default function GlyphPanel({series,busy,act}) {
  const glyphs = series.source_glyphs || [];
  const missing = glyphs.filter(g=>g.text===null).length;
  return <Paper withBorder p="lg">
    <Group justify="space-between" mb="md"><div><Title order={3}>Caractères des EPUB</Title><Text size="sm" c="dimmed" mt={4}>Certains livres représentent des caractères par de petites images. Leur transcription complète le texte source.</Text></div><Button size="sm" variant="default" loading={busy} onClick={()=>act({action:'scan-source-images',series_id:series.id},r=>`${r.books_checked} EPUB vérifiés, ${r.images_located} images repérées.`)}>Vérifier les EPUB archivés</Button></Group>
    {missing>0&&<Alert color="orange" mb="md">{missing} image(s) restent à transcrire. Les chapitres concernés ne peuvent pas être générés ni approuvés tant que leur texte source reste incomplet.</Alert>}
    {glyphs.length?<SimpleGrid cols={{base:1,sm:2,lg:3}}>{[...glyphs].sort((a,b)=>(a.text!==null)-(b.text!==null)).map(g=><GlyphCard key={`${series.id}:${g.image_hash}`} seriesId={series.id} glyph={g} busy={busy} act={act}/>)}</SimpleGrid>:<Text size="sm" c="dimmed">Aucun caractère en image repéré. Pour une ancienne importation, vérifiez les EPUB archivés.</Text>}
  </Paper>;
}
