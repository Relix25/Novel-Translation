import React, { useEffect, useEffectEvent, useRef, useState } from 'react';
import EditorialNotes from './EditorialNotes.jsx';
import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Modal,
  Pagination,
  Paper,
  ScrollArea,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { IconArrowLeft, IconArrowRight, IconCheck, IconShieldCheck } from '@tabler/icons-react';

const states = {
  approved: 'Approved',
  draft: 'To review',
  needs_review: 'Context needs review',
  imported: 'To translate',
};
export default function Workshop({
  chapter,
  chapters,
  query,
  pairAction,
  get,
  post,
  onSaved,
  onOpen,
  onClose,
  onMemory,
  onGenerate,
  onQuality,
  jobs,
  connected,
  canEdit,
  storageKey,
}) {
  const [cached] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(storageKey) || 'null');
    } catch {
      return null;
    }
  });
  const initialEdits = cached?.source_hash === chapter.source_hash ? cached.edits || {} : {};
  const [data, setData] = useState(chapter),
    [edits, setEdits] = useState(initialEdits),
    [mode, setMode] = useState('revision'),
    [page, setPage] = useState(1),
    [search, setSearch] = useState(''),
    [reason, setReason] = useState(''),
    [error, setError] = useState(''),
    [saving, setSaving] = useState(false),
    [savedAt, setSavedAt] = useState(null),
    [blocked, setBlocked] = useState(
      !!Object.keys(initialEdits).length && cached?.hash !== chapter.translation_hash,
    ),
    [confirmDiscard, setConfirmDiscard] = useState(false),
    [version, setVersion] = useState(null),
    [restoring, setRestoring] = useState(false);
  const dirty = useRef(initialEdits),
    current = useRef(chapter),
    flight = useRef(null),
    alive = useRef(true);
  const active = jobs.some(
    (j) => j.number === chapter.number && ['queued', 'running'].includes(j.state),
  );
  const previousActive = useRef(active);
  const isDirty = Object.keys(edits).length > 0;
  const currentIndex = chapters.findIndex((c) => c.number === chapter.number),
    next = chapters[currentIndex + 1],
    previous = chapters[currentIndex - 1];
  function persist() {
    if (Object.keys(dirty.current).length)
      localStorage.setItem(
        storageKey,
        JSON.stringify({
          source_hash: current.current.source_hash,
          hash: current.current.translation_hash,
          edits: dirty.current,
        }),
      );
    else localStorage.removeItem(storageKey);
  }
  function update(segment, text) {
    const nextEdits = { ...dirty.current };
    if (text === current.current.translation?.find((s) => s.id === segment.id)?.text)
      delete nextEdits[segment.id];
    else nextEdits[segment.id] = text;
    dirty.current = nextEdits;
    setEdits(nextEdits);
    persist();
  }
  async function reload() {
    const fresh = await get(`/api/chapter?${query}&number=${chapter.number}`);
    current.current = fresh;
    if (alive.current) setData(fresh);
    return fresh;
  }
  async function save() {
    if (flight.current) {
      const result = await flight.current;
      if (!result) return null;
      return save();
    }
    if (!Object.keys(dirty.current).length) return current.current;
    if (blocked || active || !canEdit) return null;
    const patch = { ...dirty.current };
    if (Object.values(patch).some((t) => !t.trim())) {
      setError('Every paragraph must retain a translation.');
      return null;
    }
    setSaving(true);
    setError('');
    const operation = (async () => {
      try {
        await post(
          pairAction('edit', {
            number: chapter.number,
            hash: current.current.translation_hash,
            packet_hash: current.current.current_packet_hash,
            edits: patch,
          }),
        );
        const fresh = await reload();
        const remaining = { ...dirty.current };
        for (const [id, text] of Object.entries(patch))
          if (remaining[id] === text) delete remaining[id];
        dirty.current = remaining;
        persist();
        if (alive.current) {
          setEdits(remaining);
          setSavedAt(Date.now());
        }
        await onSaved();
        return fresh;
      } catch (e) {
        if (alive.current) {
          setError(e.message);
          setBlocked(true);
        }
        return null;
      } finally {
        if (alive.current) setSaving(false);
      }
    })();
    flight.current = operation;
    const result = await operation;
    flight.current = null;
    return result;
  }
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const saveFromEffect = useEffectEvent(save);
  const reloadFromEffect = useEffectEvent(reload);
  useEffect(() => {
    if (!isDirty || blocked || active || !canEdit || Object.values(edits).some((t) => !t.trim()))
      return;
    const timer = setTimeout(() => saveFromEffect(), 1500);
    return () => clearTimeout(timer);
  }, [isDirty, edits, blocked, active, canEdit]);
  useEffect(() => {
    const before = (e) => {
      if (Object.keys(dirty.current).length) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', before);
    return () => window.removeEventListener('beforeunload', before);
  }, []);
  useEffect(() => {
    if (previousActive.current && !active) {
      if (Object.keys(dirty.current).length) {
        setBlocked(true);
        setError('A job just finished. Check the new version before resuming edits.');
      } else reloadFromEffect().catch((e) => setError(e.message));
    }
    previousActive.current = active;
  }, [active]);
  async function leave(number) {
    const result = await save();
    if (!result) return;
    if (number != null) onOpen(number);
    else onClose();
  }
  async function approve(andNext = false) {
    const fresh = await save();
    if (!fresh) return;
    try {
      await post(
        pairAction('review', { number: chapter.number, hash: fresh.translation_hash, reason }),
      );
      await reload();
      await onSaved();
      if (andNext && next) onOpen(next.number);
    } catch (e) {
      setError(e.message);
    }
  }
  async function generate(kind) {
    if (await save()) onGenerate(chapter.number, kind);
  }
  async function openVersion(id) {
    if (!id) {
      setVersion(null);
      return;
    }
    try {
      setVersion(await get(`/api/version?${query}&number=${chapter.number}&id=${id}`));
    } catch (e) {
      setError(e.message);
    }
  }
  async function restore() {
    const fresh = await save();
    if (!fresh) return;
    setRestoring(true);
    try {
      await post(
        pairAction('restore-version', {
          number: chapter.number,
          version_id: version.id,
          hash: fresh.translation_hash,
          packet_hash: fresh.current_packet_hash,
        }),
      );
      await reload();
      await onSaved();
      setVersion(null);
      setMode('revision');
    } catch (e) {
      setError(e.message);
    } finally {
      setRestoring(false);
    }
  }
  function exportEdits() {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            {
              chapter: chapter.number,
              hash: current.current.translation_hash,
              edits: dirty.current,
            },
            null,
            2,
          ),
        ],
        { type: 'application/json' },
      ),
    );
    a.download = `corrections-chapter-${chapter.number}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  const segments = (data.display_segments || data.segments).map((s, i) => ({
    ...s,
    index: i,
    text: edits[s.id] ?? data.translation?.[i]?.text ?? '',
  }));
  const visible = segments.filter(
    (s) => !search || `${s.source} ${s.text}`.toLowerCase().includes(search.toLowerCase()),
  );
  const pages = Math.max(1, Math.ceil(visible.length / 25)),
    safePage = Math.min(page, pages),
    slice = visible.slice((safePage - 1) * 25, safePage * 25);
  const qualityJob = jobs.find(
    (j) => j.number === chapter.number && JSON.parse(j.result || 'null')?.quality,
  );
  const changedVersion =
    version?.translation.filter((s, i) => s.text !== data.translation?.[i]?.text) || [];
  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <Button
          variant="subtle"
          color="gray"
          size="sm"
          leftSection={<IconArrowLeft size={16} />}
          onClick={() => leave()}
        >
          All chapters
        </Button>
        <Group>
          <Button
            size="xs"
            variant="default"
            disabled={!previous || saving}
            onClick={() => leave(previous.number)}
          >
            Previous
          </Button>
          <Button
            size="xs"
            variant="default"
            disabled={!next || saving}
            onClick={() => leave(next.number)}
          >
            Next
          </Button>
        </Group>
      </Group>
      <Paper withBorder p="lg">
        <Group justify="space-between" align="flex-start">
          <div>
            <Text className="eyebrow">WORKSPACE · CHAPTER {chapter.number}</Text>
            <Title order={2} mt={5}>
              {data.title}
            </Title>
            <Group mt="sm">
              <Badge color={data.state === 'approved' ? 'teal' : 'orange'} variant="light">
                {states[data.state] || data.state}
              </Badge>
              <Text size="xs" c={isDirty ? 'orange' : 'dimmed'} aria-live="polite">
                {saving
                  ? 'Saving…'
                  : isDirty
                    ? 'Local edits pending'
                    : savedAt
                      ? 'Edits saved'
                      : 'Saved version'}
              </Text>
            </Group>
          </div>
          <SegmentedControl
            aria-label="Workspace mode"
            value={mode}
            onChange={setMode}
            data={[
              { value: 'revision', label: 'Revision' },
              { value: 'reading', label: 'Reading' },
              { value: 'memory', label: 'Memory' },
              { value: 'history', label: 'History' },
            ]}
          />
        </Group>
      </Paper>
      {active && (
        <Alert color="indigo">
          An agent is working on this chapter. Reading remains available; editing resumes when the
          job finishes.
        </Alert>
      )}
      {!canEdit && (
        <Alert color="orange">Restart Novel to enable the workspace and edit history.</Alert>
      )}
      {(error || blocked) && (
        <Alert color="orange" title="Edits preserved in this browser">
          <Text size="sm">{error || 'The server version changed after your local edits.'}</Text>
          <Group mt="sm">
            <Button
              size="xs"
              variant="default"
              onClick={() => {
                setBlocked(false);
                setError('');
              }}
            >
              Retry saving
            </Button>
            <Button size="xs" variant="default" onClick={exportEdits}>
              Export my edits
            </Button>
            <Button
              size="xs"
              color="orange"
              variant="subtle"
              onClick={() => setConfirmDiscard(true)}
            >
              Discard my local edits
            </Button>
          </Group>
        </Alert>
      )}
      {data.validation_error && <Alert color="orange">{data.validation_error}</Alert>}
      {mode === 'revision' && (
        <EditorialNotes notes={data.editorial_notes} stale={data.editorial_notes_stale} />
      )}
      {!data.translation && (
        <Paper withBorder p="xl">
          <Stack align="center">
            <Title order={3}>This chapter is awaiting translation</Title>
            <Text c="dimmed" size="sm">
              Prepare a batch from the chapter list to check settings before starting.
            </Text>
            <Button onClick={() => leave()}>Choose chapters to translate</Button>
          </Stack>
        </Paper>
      )}
      {['revision', 'reading'].includes(mode) && (
        <>
          <Group justify="space-between">
            <TextInput
              placeholder="Search the source and translation…"
              aria-label="Search this chapter"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              w={360}
            />
            <Group>
              <Text size="xs" c="dimmed">
                {visible.length} paragraphs{search ? ' matching' : ''}
              </Text>
              <Pagination size="sm" total={pages} value={safePage} onChange={setPage} />
            </Group>
          </Group>
          {mode === 'revision' && data.warnings?.length > 0 && (
            <Alert color="orange" title={`${data.warnings.length} terminology issue(s) to check`}>
              <Text size="sm">
                {[...new Set(data.warnings.map((w) => `${w.term} → ${w.expected}`))]
                  .slice(0, 12)
                  .join(' · ')}
              </Text>
              <Text size="xs" mt="xs">
                Correct discrepancies or explain exceptions in your approval decision.
              </Text>
            </Alert>
          )}
          <div className={mode === 'reading' ? 'reading-page' : 'editor-page'}>
            {mode === 'revision' && (
              <div className="editor-head">
                <Text>SOURCE</Text>
                <Text>TRANSLATION · edit directly</Text>
              </div>
            )}
            {slice.map((s) =>
              mode === 'reading' ? (
                <p key={s.id} className="reading-paragraph">
                  <span>{s.index + 1}</span>
                  {s.text || 'Translation pending.'}
                </p>
              ) : (
                <div className="editor-row" key={s.id}>
                  <div className="source-prose">
                    <Text size="xs" c="dimmed" mb={8}>
                      Paragraph {s.index + 1}
                    </Text>
                    <Text style={{ whiteSpace: 'pre-wrap' }}>{s.source}</Text>
                  </div>
                  <div className="target-prose">
                    <Group justify="space-between" mb={7}>
                      <Text size="xs" c="dimmed">
                        Paragraph {s.index + 1}
                      </Text>
                      {edits[s.id] != null && (
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          color="gray"
                          onClick={() => update(s, data.translation[s.index].text)}
                        >
                          Undo edit
                        </Button>
                      )}
                    </Group>
                    <Textarea
                      aria-label={`Paragraph translation ${s.index + 1}`}
                      autosize
                      minRows={2}
                      value={s.text}
                      onChange={(e) => update(s, e.target.value)}
                      disabled={!data.translation || active || !canEdit || blocked}
                      variant="unstyled"
                      className="translation-input"
                    />
                    {data.warnings
                      ?.filter((w) => w.id === s.id)
                      .map((w) => (
                        <Text size="xs" c="orange" key={w.term}>
                          Expected term: {w.expected}
                        </Text>
                      ))}
                  </div>
                </div>
              ),
            )}
          </div>
          <Group justify="center">
            <Pagination
              total={pages}
              value={safePage}
              onChange={(p) => {
                setPage(p);
                window.scrollTo({ top: 0, behavior: 'smooth' });
              }}
            />
          </Group>
        </>
      )}
      {mode === 'memory' && (
        <Stack>
          <Paper withBorder p="lg">
            <Group justify="space-between">
              <Title order={3}>Glossary for this chapter</Title>
              <Button
                variant="light"
                size="xs"
                onClick={async () => {
                  if (await save()) onMemory(chapter.number);
                }}
              >
                Open entity records at this chapter
              </Button>
            </Group>
            <Text size="xs" c="dimmed" mt="sm" mb="md">
              Approved series terminology is available in Entities & memory.
            </Text>
            {data.glossary?.map((t, i) => (
              <Group key={i} mb="xs">
                <Text size="sm">{t.source}</Text>
                <IconArrowRight size={14} />
                <Text fw={600} size="sm">
                  {t.target}
                </Text>
              </Group>
            ))}
            {!data.glossary?.length && (
              <Text size="sm" c="dimmed">
                No applicable terms.
              </Text>
            )}
          </Paper>
          <Paper withBorder p="lg">
            <Group justify="space-between">
              <Title order={3}>Cited summary</Title>
              <Badge variant="light">
                {data.summary_state === 'approved'
                  ? 'Approved'
                  : data.summary_state === 'stale'
                    ? 'Needs review'
                    : data.summary
                      ? 'To review'
                      : 'To create'}
              </Badge>
            </Group>
            {data.summary ? (
              <>
                <Text mt="md" style={{ whiteSpace: 'pre-wrap' }}>
                  {data.summary.text}
                </Text>
                <Text size="xs" c="dimmed" mt="sm">
                  {data.summary.evidence.length} source paragraph references
                </Text>
                <ScrollArea mah={200} mt="sm">
                  {data.summary.evidence.map((id) => {
                    const s = segments.find((p) => p.id === id);
                    return (
                      <Text key={id} size="sm" mb="sm">
                        § {s ? s.index + 1 : '?'} · {s?.source}
                      </Text>
                    );
                  })}
                </ScrollArea>
              </>
            ) : (
              <Text size="sm" c="dimmed" my="md">
                Create the summary after translation approval, then approve it separately.
              </Text>
            )}
            <Group mt="md">
              <Button
                variant="light"
                disabled={data.state !== 'approved' || active || !connected || isDirty}
                onClick={() => generate('summary')}
              >
                Prepare summary · Luna Low
              </Button>
              {data.summary_state === 'draft' && (
                <Button
                  variant="default"
                  disabled={!reason.trim() || isDirty || active}
                  onClick={async () => {
                    try {
                      await post(
                        pairAction('review-summary', {
                          number: chapter.number,
                          hash: data.summary_hash,
                          reason,
                        }),
                      );
                      await reload();
                      await onSaved();
                    } catch (e) {
                      setError(e.message);
                    }
                  }}
                >
                  Approve reviewed summary
                </Button>
              )}
            </Group>
          </Paper>
        </Stack>
      )}
      {mode === 'history' && (
        <Paper withBorder p="lg">
          <Title order={3}>Version history</Title>
          <Text c="dimmed" size="sm" mt="sm" mb="lg">
            Restoring a version creates a draft for approval. Older versions remain available.
          </Text>
          <Select
            label="Version to inspect"
            searchable
            clearable
            data={(data.versions || []).map((v) => ({
              value: String(v.id),
              label: `#${v.id} · ${new Date(v.created_at.replace(' ', 'T') + 'Z').toLocaleString('en-GB')} · ${states[v.state] || v.state} · ${v.reason}`,
            }))}
            value={version ? String(version.id) : null}
            onChange={openVersion}
          />
          {!data.versions?.length && (
            <Text size="sm" c="dimmed" mt="md">
              Versions will be preserved from your next edit or approval.
            </Text>
          )}
          {version && (
            <Stack mt="lg">
              <Group justify="space-between">
                <Text size="sm">
                  {changedVersion.length} paragraphs differ from the current version
                </Text>
                <Button
                  variant="light"
                  disabled={!changedVersion.length || active || !canEdit || isDirty}
                  loading={restoring}
                  onClick={restore}
                >
                  Restore as draft
                </Button>
              </Group>
              <ScrollArea mah={500}>
                {changedVersion.map((s) => (
                  <Paper withBorder p="md" mb="sm" key={s.id}>
                    <Text size="xs" c="dimmed" mb="xs">
                      Paragraph {segments.find((p) => p.id === s.id)?.index + 1}
                    </Text>
                    <Text size="sm" c="dimmed">
                      Current: {data.translation?.find((p) => p.id === s.id)?.text}
                    </Text>
                    <Divider my="sm" />
                    <Text size="sm">Selected version: {s.text}</Text>
                  </Paper>
                ))}
              </ScrollArea>
            </Stack>
          )}
        </Paper>
      )}
      {data.translation && (
        <Paper withBorder p="lg" className="validation-panel">
          <Group justify="space-between" mb="sm">
            <Title order={3}>Your decision</Title>
            {qualityJob && (
              <Button
                variant="subtle"
                size="xs"
                leftSection={<IconShieldCheck size={15} />}
                onClick={() => onQuality(qualityJob)}
              >
                Agent report
              </Button>
            )}
          </Group>
          <Textarea
            label="Review and terminology exceptions"
            placeholder="What you checked, including any glossary exceptions…"
            autosize
            minRows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <Group justify="space-between" mt="md">
            <Group>
              <Button
                variant="default"
                loading={saving}
                disabled={!isDirty || active || blocked || !canEdit}
                onClick={save}
              >
                Save now
              </Button>
              <Button
                variant="subtle"
                disabled={active || !connected || isDirty || data.state === 'approved'}
                onClick={() => generate('quality_review')}
              >
                Run AI review again
              </Button>
            </Group>
            <Group>
              <Button
                variant="light"
                leftSection={<IconCheck size={16} />}
                disabled={!reason.trim() || active || blocked || saving || !canEdit}
                onClick={() => approve()}
              >
                Approve this version
              </Button>
              <Button
                rightSection={<IconArrowRight size={16} />}
                disabled={!reason.trim() || !next || active || blocked || saving || !canEdit}
                onClick={() => approve(true)}
              >
                Approve and next
              </Button>
            </Group>
          </Group>
          <Text size="xs" c="dimmed" mt="sm">
            Manual edits use no tokens. Final approval is yours.
          </Text>
        </Paper>
      )}
      <Modal
        opened={confirmDiscard}
        onClose={() => setConfirmDiscard(false)}
        title="Discard local edits?"
      >
        <Stack>
          <Text size="sm">
            The latest saved server version will be reloaded. Export your edits first if you want to
            keep them.
          </Text>
          <Button
            color="orange"
            onClick={async () => {
              try {
                await reload();
                dirty.current = {};
                setEdits({});
                localStorage.removeItem(storageKey);
                setBlocked(false);
                setError('');
                setConfirmDiscard(false);
              } catch (e) {
                setError(e.message);
              }
            }}
          >
            Discard and reload
          </Button>
        </Stack>
      </Modal>
    </Stack>
  );
}
