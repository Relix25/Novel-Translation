import React, { useEffect, useState } from 'react';
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Collapse,
  Group,
  Modal,
  NumberInput,
  Paper,
  Progress,
  ScrollArea,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';

export const defaultLimits = {
  max_tokens: 750000,
  max_calls: 64,
  timeout_seconds: 600,
  idle_seconds: 120,
};
const fmt = (n) => Number(n || 0).toLocaleString('en-GB');
const credit = (n) =>
  n == null ? 'unavailable' : Number(n).toLocaleString('en-GB', { maximumFractionDigits: 3 });
const phases = {
  preparing: 'Preparation',
  translation: 'Translation',
  quality_review: 'Review',
  summary: 'Summary',
  memory: 'Story entities',
};
const statuses = {
  queued: 'Queued',
  running: 'Running',
  draft: 'Ready for review',
  failed: 'Failed',
  interrupted: 'Interrupted',
  paused: 'Paused',
  pause_requested: 'Pause after call',
  completed: 'Completed',
  cancelled: 'Cancelled',
};
function seconds(date, clock) {
  if (!date) return null;
  const parsed = Date.parse(date.includes('T') ? date : date.replace(' ', 'T') + 'Z');
  return Number.isFinite(parsed) ? Math.max(0, Math.floor((clock - parsed) / 1000)) : null;
}
function duration(n) {
  return n == null ? '—' : n < 60 ? `${n} s` : `${Math.floor(n / 60)} min ${n % 60} s`;
}

export function LimitFields({ value, onChange }) {
  const set = (key, n) => onChange({ ...value, [key]: n });
  return (
    <Stack gap="sm">
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <NumberInput
          label="Token limit"
          min={1000}
          max={100000000}
          step={50000}
          value={value.max_tokens}
          onChange={(n) => set('max_tokens', n)}
          thousandSeparator=" "
        />
        <NumberInput
          label="Maximum calls"
          min={1}
          max={1000}
          value={value.max_calls}
          onChange={(n) => set('max_calls', n)}
        />
        <NumberInput
          label="Maximum call duration (s)"
          min={30}
          max={1200}
          value={value.timeout_seconds}
          onChange={(n) => set('timeout_seconds', n)}
        />
        <NumberInput
          label="Stop after inactivity (s)"
          min={15}
          max={600}
          value={value.idle_seconds}
          onChange={(n) => set('idle_seconds', n)}
        />
      </SimpleGrid>
      <Text size="xs" c="dimmed">
        Checked between calls and on each Codex usage report. A call may exceed the limit before
        reporting usage. No automatic restart.
      </Text>
    </Stack>
  );
}

export function JobCard({ job, series, clock, act, showQuality, busy, onOpen }) {
  const p = job.progress || {},
    active = ['queued', 'running'].includes(job.state),
    report = JSON.parse(job.result || 'null')?.quality;
  const finalClock = job.finished_at ? Date.parse(job.finished_at) : clock;
  const done = p.paragraphs_done || 0,
    total = p.paragraphs_total || 0;
  return (
    <Paper withBorder p="lg">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <div>
            <Text size="xs" c="dimmed" lineClamp={1}>
              {series?.title}
            </Text>
            <Text fw={650}>
              Chapter {job.number} · {phases[p.phase || job.kind] || 'Processing'}
            </Text>
            <Text size="sm" c="dimmed">
              {p.model || job.model} · {p.effort || job.effort} · {job.source} → {job.target}
            </Text>
          </div>
          <Badge color={job.error ? 'orange' : active ? 'indigo' : 'gray'} variant="light">
            {job.stop_requested && active
              ? 'Stop requested'
              : job.error && job.state === 'draft'
                ? 'Draft saved · stopped'
                : statuses[job.state] || job.state}
          </Badge>
        </Group>
        {total > 0 && (
          <>
            <Group justify="space-between">
              <Text size="sm">
                {fmt(done)} / {fmt(total)} paragraphs processed in this phase
              </Text>
              <Text size="xs" c="dimmed">
                Batch {p.batch} / {p.batch_total}
                {p.phase === 'quality_review' ? ` · pass ${p.pass_number}` : ''}
              </Text>
            </Group>
            <Progress
              value={Math.min(100, (done / total) * 100)}
              animated={active && !job.stop_requested}
            />
          </>
        )}
        <Group gap="lg">
          <Text size="xs">Duration: {duration(seconds(job.started_at, finalClock))}</Text>
          <Text size="xs">
            {job.usage_known
              ? `${fmt(job.tokens)} measured tokens`
              : job.tokens
                ? `${fmt(job.tokens)} known tokens · partial reading`
                : 'Tokens not reported'}{' '}
            · {job.call_count || 0} tracked calls
          </Text>
        </Group>
        {active && (
          <>
            <Text size="xs" c="dimmed">
              {p.paragraph_start ? `Passage ${p.paragraph_start}–${p.paragraph_end} · ` : ''}Last
              activity: {duration(seconds(p.last_event_at, clock))}
              {p.activity === 'reasoning' ? ' · reasoning in progress' : ''}
              {p.output_chars ? ` · ${fmt(p.output_chars)} characters received` : ''}
            </Text>
            <Group>
              <Button
                color="orange"
                size="xs"
                variant="light"
                disabled={busy || !!job.stop_requested}
                onClick={() =>
                  act(
                    { action: 'stop-job', job_id: job.id },
                    'Stop requested. Validated batches remain available for resume.',
                  )
                }
              >
                Stop this job
              </Button>
            </Group>
          </>
        )}
        {job.error && (
          <Alert color="orange" py="xs">
            {job.error}
          </Alert>
        )}
        {report && (
          <Button variant="subtle" size="compact-sm" onClick={() => showQuality(job)}>
            Review report · {report.checked_batches}/{report.batch_total} batches
          </Button>
        )}
        {onOpen && (
          <Button variant="light" size="sm" onClick={() => onOpen(job)}>
            {job.kind === 'memory' ? 'Open entity records' : 'Open in workspace'}
          </Button>
        )}
        {!active && job.call_count === 0 && (
          <Text size="xs" c="dimmed">
            Older job: view details in Usage.
          </Text>
        )}
      </Stack>
    </Paper>
  );
}

function RunCard({ run, act, busy, series }) {
  const [edit, setEdit] = useState(false),
    [budget, setBudget] = useState(run.options.limits);
  const limitsSignature = JSON.stringify(run.options.limits);
  useEffect(() => {
    setBudget(JSON.parse(limitsSignature));
  }, [limitsSignature]);
  const complete = run.items.filter((i) => i.state === 'done').length,
    active = ['queued', 'running', 'pause_requested'].includes(run.state);
  return (
    <Paper withBorder p="lg" bg="indigo.0">
      <Stack gap="sm">
        <Group justify="space-between">
          <div>
            <Text size="xs" c="dimmed">
              {series?.title}
            </Text>
            <Title order={4}>
              Batch translation · {complete}/{run.items.length} chapters
            </Title>
          </div>
          <Badge variant="light">{statuses[run.state]}</Badge>
        </Group>
        <Progress value={(100 * complete) / run.items.length} />
        <Text size="sm">
          {run.source} → {run.target} · {fmt(run.tokens)} / {fmt(run.options.limits.max_tokens)}{' '}
          tokens · {run.call_count} / {run.options.limits.max_calls} calls
        </Text>
        <Group gap={6}>
          {run.items.map((i) => (
            <Badge
              key={i.position}
              color={
                i.state === 'done'
                  ? 'teal'
                  : i.state === 'failed'
                    ? 'orange'
                    : i.state === 'running'
                      ? 'indigo'
                      : 'gray'
              }
              variant="light"
            >
              Ch. {i.number} ·{' '}
              {i.state === 'done'
                ? 'ready'
                : i.state === 'failed'
                  ? 'stopped'
                  : i.state === 'running'
                    ? 'in progress'
                    : 'pending'}
            </Badge>
          ))}
        </Group>
        {run.error && <Alert color="orange">{run.error}</Alert>}
        <Group>
          {active && (
            <Button
              variant="subtle"
              color="red"
              disabled={busy}
              onClick={() =>
                act(
                  { action: 'bulk-control', run_id: run.id, command: 'pause' },
                  'Immediate stop requested. The last call may remain incomplete.',
                )
              }
            >
              Stop immediately
            </Button>
          )}
          {active && (
            <Button
              variant="light"
              color="orange"
              disabled={busy || run.state === 'pause_requested'}
              onClick={() =>
                act({ action: 'bulk-control', run_id: run.id, command: 'pause-after-call' })
              }
            >
              Pause after the current call
            </Button>
          )}
          {run.state === 'paused' && (
            <>
              <Button
                disabled={busy}
                onClick={() =>
                  act(
                    { action: 'bulk-control', run_id: run.id, command: 'resume', limits: budget },
                    'Resume requested from the first remaining chapter.',
                  )
                }
              >
                Resume
              </Button>
              <Button variant="default" onClick={() => setEdit(!edit)}>
                Change limits
              </Button>
            </>
          )}
          {['paused', 'queued'].includes(run.state) && (
            <Button
              disabled={busy}
              color="gray"
              variant="subtle"
              onClick={() =>
                act(
                  { action: 'bulk-control', run_id: run.id, command: 'cancel' },
                  'Queue cancelled; results are preserved.',
                )
              }
            >
              Cancel queue
            </Button>
          )}
        </Group>
        <Collapse in={edit && run.state === 'paused'}>
          <LimitFields value={budget} onChange={setBudget} />
          <Text size="xs" mt="sm">
            Resuming preserves all tokens already used.
          </Text>
        </Collapse>
      </Stack>
    </Paper>
  );
}

export function ActivityPanel({
  jobs,
  runs,
  series,
  act,
  showQuality,
  busy,
  onOpen,
  compact = false,
}) {
  const [clock, setClock] = useState(Date.now()),
    [history, setHistory] = useState(false);
  const active = jobs.filter((j) => ['running', 'queued'].includes(j.state));
  const openRuns = runs.filter((r) => !['completed', 'cancelled'].includes(r.state));
  useEffect(() => {
    if (!active.length) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active.length]);
  if (compact && !active.length && !openRuns.length) return null;
  return (
    <Stack mb={compact ? 'lg' : 0}>
      {(compact ? openRuns : runs).map((r) => (
        <RunCard
          key={r.id}
          run={r}
          act={act}
          busy={busy}
          series={series.find((s) => s.id === r.series)}
        />
      ))}
      {active.map((j) => (
        <JobCard
          key={j.id}
          job={j}
          clock={clock}
          series={series.find((s) => s.id === j.series)}
          act={act}
          busy={busy}
          showQuality={showQuality}
          onOpen={onOpen}
        />
      ))}
      {!compact && (
        <>
          <Group justify="space-between">
            <Title order={3}>Recent jobs</Title>
            <Button variant="subtle" onClick={() => setHistory(!history)}>
              {history ? 'Collapse' : 'Show all'}
            </Button>
          </Group>
          {jobs
            .filter((j) => !active.includes(j))
            .slice(0, history ? 100 : 8)
            .map((j) => (
              <JobCard
                key={j.id}
                job={j}
                clock={clock}
                series={series.find((s) => s.id === j.series)}
                act={act}
                busy={busy}
                showQuality={showQuality}
                onOpen={onOpen}
              />
            ))}
          {!jobs.length && !runs.length && (
            <Paper withBorder p="xl">
              <Text c="dimmed">No jobs yet. Start a chapter or prepare a batch from a series.</Text>
            </Paper>
          )}
        </>
      )}
    </Stack>
  );
}

export function BulkDialog({
  opened,
  onClose,
  chapters,
  numbers,
  base,
  chapterLimits,
  post,
  onStarted,
  seriesTitle,
  style,
  glossaryCount,
}) {
  const [budget, setBudget] = useState({ ...defaultLimits, max_tokens: 5000000, max_calls: 512 }),
    [plan, setPlan] = useState(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [advanced, setAdvanced] = useState(false);
  const payload = { ...base, numbers, limits: budget, chapter_limits: chapterLimits };
  const signature = JSON.stringify(payload);
  useEffect(() => {
    setPlan(null);
  }, [signature]);
  const selected = chapters.filter((c) => numbers.includes(c.number));
  async function request(start) {
    setBusy(true);
    setError('');
    try {
      const result = await post({
        ...payload,
        action: start ? 'bulk-start' : 'bulk-preview',
        ...(start ? { fingerprint: plan.fingerprint } : {}),
      });
      if (start) {
        onClose();
        await onStarted();
      } else setPlan(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal opened={opened} onClose={busy ? () => {} : onClose} title="Prepare your batch" size="lg">
      <Stack>
        <Text fw={650}>{seriesTitle}</Text>
        <Text size="sm">
          {base.source.toUpperCase()} → {base.target.toUpperCase()} · {numbers.length} chapters ·
          reading order
        </Text>
        <Paper withBorder p="md">
          <Text fw={600} size="sm">
            Exact selection
          </Text>
          <ScrollArea mah={200}>
            <Stack gap={5} mt="sm">
              {selected.map((c) => (
                <Text size="sm" key={c.number}>
                  {c.origin?.volume ? `Volume ${c.origin.volume} · ` : ''}
                  {c.number} — {c.title}
                </Text>
              ))}
            </Stack>
          </ScrollArea>
          <Button size="compact-xs" variant="subtle" mt="sm" onClick={onClose}>
            Change selection
          </Button>
        </Paper>
        <Paper withBorder p="md">
          <Text size="sm" fw={600}>
            Translation: {base.model} · {base.effort}
          </Text>
          <Text size="sm">
            {base.review
              ? `Review: ${base.review.model} · High · at most two passes`
              : 'No automatic review'}
          </Text>
          <Text size="xs" c="dimmed" mt="sm">
            {glossaryCount} concepts in the series glossary. Applicable terms are supplied for each
            chapter.
          </Text>
          <Text size="sm" mt="sm">
            {style}
          </Text>
        </Paper>
        <Alert color="indigo">
          Pause on the first error. Each result is available in the workspace for your review and
          approval.
        </Alert>
        <Button variant="subtle" onClick={() => setAdvanced(!advanced)}>
          {advanced ? 'Hide safeguards' : 'Adjust usage limits'}
        </Button>
        <Collapse in={advanced}>
          <LimitFields value={budget} onChange={setBudget} />
          <Text size="xs" c="dimmed" mt="sm">
            Per chapter: {fmt(chapterLimits.max_tokens)} tokens and {chapterLimits.max_calls} calls
            maximum. The strictest limit applies.
          </Text>
        </Collapse>
        <Button variant="light" loading={busy} onClick={() => request(false)}>
          Check batch and estimate usage
        </Button>
        {error && <Alert color="red">{error}</Alert>}
        {plan && (
          <>
            <Alert color="teal" title={`${plan.chapters.length} chapters ready`}>
              <Text size="sm">
                {fmt(plan.chapters.reduce((n, c) => n + c.paragraphs, 0))} paragraphs ·{' '}
                {fmt(plan.chapters.reduce((n, c) => n + c.characters, 0))} source characters
              </Text>
            </Alert>
            <Alert color="indigo" title="Illustrative estimate">
              <Text size="sm">
                {fmt(plan.estimate.tokens_low)}–{fmt(plan.estimate.tokens_high)} tokens
              </Text>
              <Text size="xs" mt="xs">
                {plan.estimate.basis}
              </Text>
              <Text size="xs" mt="xs">
                {credit(plan.estimate.credits_low)}–{credit(plan.estimate.credits_high)} estimated
                credits · no conversion to a percentage of included quota.
              </Text>
              <Anchor size="xs" href={plan.estimate.rates_url} target="_blank" rel="noreferrer">
                Rates dated {plan.estimate.rates_date}
              </Anchor>
            </Alert>
            {plan.estimate.tokens_high > budget.max_tokens && (
              <Text size="sm" c="orange">
                The limit is below the upper estimate: the run may pause before completion.
              </Text>
            )}
            <Button loading={busy} onClick={() => request(true)}>
              Start batch · {plan.chapters.length} chapters
            </Button>
          </>
        )}
      </Stack>
    </Modal>
  );
}

export function UsagePanel({ query, epoch, get }) {
  const [data, setData] = useState(null),
    [error, setError] = useState(''),
    [detail, setDetail] = useState(null);
  useEffect(() => {
    let current = true;
    get(`/api/usage?${query}`)
      .then((d) => {
        if (current) {
          setData(d);
          setError('');
        }
      })
      .catch((e) => {
        if (current) setError(e.message);
      });
    return () => {
      current = false;
    };
  }, [query, epoch, get]);
  const rows = data?.chapters || [],
    total = rows.reduce((s, c) => s + c.total, 0),
    cost = rows.some((c) => c.credits != null)
      ? rows.reduce((s, c) => s + (c.credits || 0), 0)
      : null,
    partial = rows.some((c) => !c.complete);
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>Usage by chapter</Title>
        <Button
          component="a"
          href={`/api/usage.csv?${query}`}
          download="novel-consommation.csv"
          variant="default"
        >
          Export CSV
        </Button>
      </Group>
      {error && <Alert color="red">{error}</Alert>}
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <Paper withBorder p="lg">
          <Text size="xs" c="dimmed">
            MEASURED TOKENS
          </Text>
          <Title order={2}>{fmt(total)}</Title>
        </Paper>
        <Paper withBorder p="lg">
          <Text size="xs" c="dimmed">
            ESTIMATED CREDITS {partial ? '· PARTIAL' : ''}
          </Text>
          <Title order={2}>{credit(cost)}</Title>
        </Paper>
        <Paper withBorder p="lg">
          <Text size="xs" c="dimmed">
            SCOPE
          </Text>
          <Text fw={600}>All jobs for this language pair</Text>
          <Text size="xs" c="dimmed">
            Translation, review, summaries, entity analysis and retries
          </Text>
        </Paper>
      </SimpleGrid>
      {data && (
        <Text size="sm" c="dimmed">
          {data.note}{' '}
          <Anchor href={data.rates_url} target="_blank" rel="noreferrer" size="sm">
            Rates dated {data.rates_date}
          </Anchor>
        </Text>
      )}
      {partial && (
        <Alert color="orange">
          Some older calls, interrupted calls or models have no complete usage report. Displayed
          totals are partial.
        </Alert>
      )}
      <Paper withBorder p="md">
        <ScrollArea>
          <Table miw={780}>
            <Table.Thead>
              <Table.Tr>
                {[
                  'Chapter',
                  'Calls',
                  'Input / cached input',
                  'Output / included reasoning',
                  'Total tokens',
                  'Estimated credits',
                  '',
                ].map((t) => (
                  <Table.Th key={t}>{t}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((c) => (
                <Table.Tr key={c.number}>
                  <Table.Td>
                    <Text fw={600}>Ch. {c.number}</Text>
                    <Text size="xs" lineClamp={1} maw={190}>
                      {c.title}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {c.calls}
                    <Text size="xs" c="dimmed">
                      {c.jobs} travaux
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {fmt(c.input)} / {fmt(c.cached)}
                  </Table.Td>
                  <Table.Td>
                    {fmt(c.output)} / {fmt(c.reasoning)}
                  </Table.Td>
                  <Table.Td>{fmt(c.total)}</Table.Td>
                  <Table.Td>
                    {credit(c.credits)}
                    {!c.complete ? ' *' : ''}
                  </Table.Td>
                  <Table.Td>
                    <Button size="compact-xs" variant="subtle" onClick={() => setDetail(c)}>
                      Details
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
        {!rows.length && (
          <Text p="lg" c="dimmed">
            No calls recorded for this language pair.
          </Text>
        )}
      </Paper>
      <Modal
        opened={!!detail}
        onClose={() => setDetail(null)}
        title={`Usage · chapter ${detail?.number}`}
        size="lg"
      >
        <Stack>
          {detail?.operations.map((o, i) => (
            <Paper withBorder p="md" key={i}>
              <Text fw={600}>
                {phases[o.phase]} · {o.model} {o.effort}
              </Text>
              <Text size="sm">
                {fmt(o.usage.inputTokens)} input · {fmt(o.usage.outputTokens)} output ·{' '}
                {credit(o.credits)} estimated credits
              </Text>
              <Text size="xs" c="dimmed">
                {o.complete ? 'Usage available' : 'Usage incomplete'} · {o.state} · job{' '}
                {o.job.slice(0, 8)}
              </Text>
            </Paper>
          ))}
        </Stack>
      </Modal>
    </Stack>
  );
}
