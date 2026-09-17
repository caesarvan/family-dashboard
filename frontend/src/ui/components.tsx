import type { ReactNode } from 'react';
import { StyleSheet, View, useWindowDimensions, type StyleProp, type ViewStyle } from 'react-native';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { Card, Text, useTheme } from 'react-native-paper';
import { expoTokens, useDisplayDensity } from './theme';

export type SectionCardProps = {
  title: string;
  action?: ReactNode;
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
};

export function SectionCard({ title, action, children, style }: SectionCardProps) {
  const theme = useTheme();
  const narrow = useWindowDimensions().width < expoTokens.compactBreakpoint;
  const density = useDisplayDensity();
  return (
    <Card mode="contained" style={[styles.card, {
      backgroundColor: theme.colors.surfaceVariant,
      borderRadius: narrow ? expoTokens.cardRadiusCompact : expoTokens.cardRadius,
    }, style]}>
      <Card.Content testID="section-card-content" style={{ paddingHorizontal: narrow ? density.cardPaddingNarrow : density.cardPadding, paddingVertical: narrow ? density.cardPaddingNarrow : density.cardPadding }}>
        <View style={[styles.sectionHeading, { marginBottom: density.sectionGap }]}>
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
  const narrow = useWindowDimensions().width < expoTokens.compactBreakpoint;
  const density = useDisplayDensity();
  return (
    <View style={[styles.pageHeader, { gap: narrow ? density.pageGapNarrow : density.pageGap, marginBottom: narrow ? density.pageBottomNarrow : density.pageBottom }]}>
      <View style={styles.pageCopy}>
        <Text variant={narrow ? 'headlineSmall' : 'headlineLarge'} accessibilityRole="header">{title}</Text>
        {description ? <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant, marginTop: 8 }}>{description}</Text> : null}
      </View>
      {action ? <View style={styles.pageAction}>{action}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 0, overflow: 'hidden' },
  sectionHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  sectionTitle: { flex: 1, minWidth: 0 },
  sectionAction: { flexShrink: 1, maxWidth: '50%' },
  empty: { paddingHorizontal: 12, paddingVertical: 18, gap: 8, alignItems: 'center' },
  emptyText: { textAlign: 'center', maxWidth: 460 },
  emptyAction: { marginTop: 6, maxWidth: '100%' },
  pageHeader: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap' },
  pageCopy: { flexGrow: 1, flexShrink: 1, flexBasis: 200, minWidth: 0 },
  pageAction: { flexShrink: 1, maxWidth: '100%' },
});
