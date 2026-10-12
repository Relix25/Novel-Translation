import React from 'react';
import { Alert, Badge, Divider, Group, Paper, Stack, Text, Title } from '@mantine/core';

export const qualityLabel = {running:'Review in progress',checked:'AI checked',needs_attention:'Needs attention',interrupted:'Review interrupted'};
const verdictLabel = {clean:'No issues flagged',corrected:'Corrected',uncertain:'Uncertainty'};
const categoryLabel = {meaning:'Meaning',omission:'Omission',addition:'Addition',name:'Name',number:'Number',voice:'Character voice',style:'Style',ambiguity:'Ambiguity'};
export default function QualityReport({report}) {
  return <Stack gap="md">
    <Group justify="space-between"><Badge color={report.status==='checked'?'teal':'orange'}>{qualityLabel[report.status]||report.status}</Badge><Text size="sm">{report.model} · {report.effort}</Text></Group>
    {!report.is_current&&<Alert color="orange">The text or context changed since this report. A new review is required.</Alert>}
    <Text size="sm">{report.checked_batches} / {report.batch_total} batches with no issues flagged · {report.call_count} calls · {report.correction_count} corrections · {report.unresolved_count} issues to examine.</Text>
    <Text size="sm" c="dimmed">At most two passes per batch. A correction made on the final pass still requires confirmation. Final chapter and summary approval remain separate.</Text>
    {report.error&&<Alert color="red">{report.error}</Alert>}
    {report.token_usage_complete===false&&<Alert color="orange">Some calls did not report usage. The displayed total is incomplete.</Alert>}
    {(report.unresolved||[]).map((issue,i)=><Paper withBorder p="md" key={`issue-${i}`}><Text fw={600} size="sm">To examine · {issue.id}</Text><Text size="sm" mt="xs">{issue.detail}</Text><Text size="sm" c="dimmed" mt="xs">Source: {issue.source_quote}</Text></Paper>)}
    <Divider/><Title order={4}>Decisions and corrections</Title>
    {(report.calls||[]).map((call,i)=><Paper withBorder p="md" key={i}><Group justify="space-between"><Text fw={600}>Batch {call.batch} · pass {call.pass}</Text><Badge variant="light">{verdictLabel[call.response.verdict]}</Badge></Group><Text size="sm" c="dimmed" mt="xs">{call.response.note||'Comparison completed.'}</Text>{call.response.corrections.map(c=><Stack key={c.id} gap="xs" mt="md"><Text size="xs" fw={600}>{c.id} · {categoryLabel[c.category]}</Text><Text size="sm">Source: {c.source_quote}</Text><Text size="sm" c="dimmed">Before: {c.before}</Text><Text size="sm">After: {c.after}</Text><Text size="sm" c="indigo">{c.reason}</Text></Stack>)}</Paper>)}
  </Stack>;
}
