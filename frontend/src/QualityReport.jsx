import React from 'react';
import { Alert, Badge, Divider, Group, Paper, Stack, Text, Title } from '@mantine/core';

export const qualityLabel = {running:'Vérification en cours',checked:'Vérifié par IA',needs_attention:'Points à examiner',interrupted:'Vérification interrompue'};
const verdictLabel = {clean:'Sans réserve',corrected:'Corrigé',uncertain:'Incertitude'};
const categoryLabel = {meaning:'Sens',omission:'Omission',addition:'Ajout',name:'Nom',number:'Nombre',voice:'Voix du personnage',style:'Style',ambiguity:'Ambiguïté'};
export default function QualityReport({report}) {
  return <Stack gap="md">
    <Group justify="space-between"><Badge color={report.status==='checked'?'teal':'orange'}>{qualityLabel[report.status]||report.status}</Badge><Text size="sm">{report.model} · {report.effort}</Text></Group>
    {!report.is_current&&<Alert color="orange">Le texte ou son contexte a changé depuis ce rapport. Une nouvelle vérification est nécessaire.</Alert>}
    <Text size="sm">{report.checked_batches} / {report.batch_total} lots sans réserve · {report.call_count} appels · {report.correction_count} corrections · {report.unresolved_count} points à examiner.</Text>
    <Text size="sm" c="dimmed">Deux passes maximum par lot. Une correction apportée à la dernière passe reste à confirmer. La validation finale du chapitre et celle du résumé restent séparées.</Text>
    {report.error&&<Alert color="red">{report.error}</Alert>}
    {report.token_usage_complete===false&&<Alert color="orange">Certains appels n’ont pas fourni leur consommation. Le total affiché est incomplet.</Alert>}
    {(report.unresolved||[]).map((issue,i)=><Paper withBorder p="md" key={`issue-${i}`}><Text fw={600} size="sm">À examiner · {issue.id}</Text><Text size="sm" mt="xs">{issue.detail}</Text><Text size="sm" c="dimmed" mt="xs">Source : {issue.source_quote}</Text></Paper>)}
    <Divider/><Title order={4}>Décisions et corrections</Title>
    {(report.calls||[]).map((call,i)=><Paper withBorder p="md" key={i}><Group justify="space-between"><Text fw={600}>Lot {call.batch} · passe {call.pass}</Text><Badge variant="light">{verdictLabel[call.response.verdict]}</Badge></Group><Text size="sm" c="dimmed" mt="xs">{call.response.note||'Comparaison terminée.'}</Text>{call.response.corrections.map(c=><Stack key={c.id} gap="xs" mt="md"><Text size="xs" fw={600}>{c.id} · {categoryLabel[c.category]}</Text><Text size="sm">Source : {c.source_quote}</Text><Text size="sm" c="dimmed">Avant : {c.before}</Text><Text size="sm">Après : {c.after}</Text><Text size="sm" c="indigo">{c.reason}</Text></Stack>)}</Paper>)}
  </Stack>;
}
