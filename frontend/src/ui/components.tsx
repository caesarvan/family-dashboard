import type { ReactNode } from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { Card, Text, useTheme } from 'react-native-paper';

export type SectionCardProps = {
  title: string;
  action?: ReactNode;
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
};

export function SectionCard({ title, action, children, style }: SectionCardProps) {
  const theme = useTheme();
  return (
    <Card mode="outlined" style={[styles.card, { backgroundColor: theme.colors.surface, borderColor: theme.colors.outline }, style]}>
      <Card.Content style={styles.cardContent}>
        <View style={styles.sectionHeading}>
          <Text variant="titleMedium" accessibilityRole="header" style={styles.sectionTitle}>{title}</Text>
          {action ? <View style={styles.sectionAction}>{action}</View> : null}
        </View>
        {children}
      </Card.Content>
    </Card>
  );
}

export type EmptyStateProps = { title: string; description?: string; action?: ReactNode };

export function EmptyState({ title, description, action }: EmptyStateProps) {
  const theme = useTheme();
  return (
    <View style={styles.empty}>
      <MaterialCommunityIcons name="inbox-outline" size={28} color={theme.colors.onSurfaceVariant} accessibilityElementsHidden importantForAccessibility="no" />
      <Text variant="titleSmall" style={styles.emptyText}>{title}</Text>
      {description ? <Text variant="bodyMedium" style={[styles.emptyText, { color: theme.colors.onSurfaceVariant }]}>{description}</Text> : null}
      {action ? <View style={styles.emptyAction}>{action}</View> : null}
    </View>
  );
}

export type PageHeaderProps = { title: string; description?: string; action?: ReactNode };

export function PageHeader({ title, description, action }: PageHeaderProps) {
  const theme = useTheme();
  return (
    <View style={styles.pageHeader}>
      <View style={styles.pageCopy}>
        <Text variant="headlineSmall" accessibilityRole="header">{title}</Text>
        {description ? <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant, marginTop: 4 }}>{description}</Text> : null}
      </View>
      {action ? <View style={styles.pageAction}>{action}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderRadius: 12, overflow: 'hidden' },
  cardContent: { paddingHorizontal: 24, paddingVertical: 24 },
  sectionHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 14 },
  sectionTitle: { flex: 1, minWidth: 0 },
  sectionAction: { flexShrink: 1, maxWidth: '50%' },
  empty: { paddingHorizontal: 12, paddingVertical: 18, gap: 8, alignItems: 'center' },
  emptyText: { textAlign: 'center', maxWidth: 460 },
  emptyAction: { marginTop: 6, maxWidth: '100%' },
  pageHeader: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 20 },
  pageCopy: { flexGrow: 1, flexShrink: 1, flexBasis: 200, minWidth: 0 },
  pageAction: { flexShrink: 1, maxWidth: '100%' },
});
