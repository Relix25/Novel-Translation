import React from 'react';
import { Alert, Badge, Paper, Stack, Text, Title } from '@mantine/core';

const labels = {
  ambiguity: 'Unresolved ambiguity',
  source_error: 'Possible source error',
  continuity_conflict: 'Continuity conflict',
  wordplay: 'Wordplay loss',
  terminology: 'Proposed terminology',
};

export default function EditorialNotes({ notes = [], stale = false }) {
  if (!notes.length) return null;
  return (
    <Paper withBorder p="lg">
      <Stack gap="md">
        <Title order={3}>Editorial notes — not for publication</Title>
        <Text size="sm" c="dimmed">
          These proposals are separate from the translation. They do not approve facts or change the
          glossary.
        </Text>
        {stale && (
          <Alert color="orange">
            The chapter context changed. Check these notes against the current source before using
            them.
          </Alert>
        )}
        {notes.map((note, index) => (
          <Paper key={`${note.id}-${index}`} withBorder p="md">
            <Badge variant="light" color="orange">
              {labels[note.category] || note.category}
            </Badge>
            <Text size="xs" c="dimmed" mt="sm">
              Source segment {note.id}
            </Text>
            <Text size="sm" mt="xs" style={{ whiteSpace: 'pre-wrap' }}>
              {note.source_quote}
            </Text>
            {note.rendering && (
              <Text size="sm" mt="sm">
                Chosen rendering: {note.rendering}
              </Text>
            )}
            <Text size="sm" mt="sm">
              {note.detail}
            </Text>
          </Paper>
        ))}
      </Stack>
    </Paper>
  );
}
