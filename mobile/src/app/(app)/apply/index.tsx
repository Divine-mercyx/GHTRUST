import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { loans } from '@/api/endpoints';
import { messageFor } from '@/api/errors';
import type { LoanProduct } from '@/api/types';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, EmptyState, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { maxTenureMonths } from '@/features/apply/config';
import { eligibilityLines } from '@/lib/eligibility';
import { keys, useApplications, useProducts } from '@/lib/queries';
import { CADENCE } from '@/lib/status';
import { colors, font, radius, space } from '@/theme/tokens';

const ICONS: Record<string, keyof typeof Ionicons.glyphMap> = {
  business_loan: 'storefront-outline',
  payday_loan: 'briefcase-outline',
  study_loan: 'school-outline',
  asset_loan: 'car-outline',
};

export default function ChooseProduct() {
  const queryClient = useQueryClient();
  const products = useProducts();
  const applications = useApplications();
  const drafts = (applications.data?.items ?? []).filter((a) => a.status === 'draft');

  const create = useMutation({
    mutationFn: (code: string) => loans.createApplication(code),
    onSuccess: (app) => {
      queryClient.setQueryData(keys.application(app.id), app);
      queryClient.invalidateQueries({ queryKey: keys.applications });
      router.replace(`/apply/${app.id}`);
    },
  });

  const choose = (p: LoanProduct) => {
    const existing = drafts.find((d) => d.product_code === p.code);
    if (existing) router.replace(`/apply/${existing.id}`);
    else create.mutate(p.code);
  };

  const available = (products.data ?? []).filter((p) => p.is_active && p.workflow_steps.length > 0);

  return (
    <Screen edges={['bottom']}>
      <Text muted>Choose the loan that fits. You can save your application and finish it later.</Text>
      {create.error ? <Banner message={messageFor(create.error)} /> : null}
      {products.isPending ? (
        <>
          <CardSkeleton />
          <CardSkeleton />
        </>
      ) : products.isError ? (
        <ErrorState error={products.error} onRetry={() => products.refetch()} />
      ) : available.length === 0 ? (
        <EmptyState
          icon="cash-outline"
          title="No loans available right now"
          body="We're setting up our loan products. Check back soon, or contact us if you need help."
          action={{ title: 'Try again', onPress: () => products.refetch() }}
        />
      ) : (
        available.map((p, i) => {
          const rules = eligibilityLines(p.eligibility_rules as Record<string, unknown>);
          const draft = drafts.find((d) => d.product_code === p.code);
          const busy = create.isPending && create.variables === p.code;
          return (
            <Animated.View key={p.code} entering={FadeInDown.delay(i * 60).duration(300)}>
              <Card onPress={create.isPending ? undefined : () => choose(p)} accessibilityLabel={`${p.name}. ${p.description ?? ''}`}>
                <View style={styles.row}>
                  <View style={styles.icon}>
                    <Ionicons name={ICONS[p.code] ?? 'cash-outline'} size={24} color={colors.navy} />
                  </View>
                  <View style={{ flex: 1, gap: 4 }}>
                    <Text variant="heading">{p.name}</Text>
                    {p.description ? (
                      <Text variant="small" muted>
                        {p.description}
                      </Text>
                    ) : null}
                  </View>
                  {busy ? <ActivityIndicator color={colors.navy} /> : <Ionicons name="chevron-forward" size={20} color={colors.textFaint} />}
                </View>
                <View style={styles.chips}>
                  <Chip text={`${Number(p.interest_rate_pct_monthly)}% monthly`} />
                  <Chip text={`${Number(p.processing_fee_pct)}% fee`} />
                  <Chip text={p.repayment_cadence_options.map((c) => CADENCE[c] ?? c).join(' / ')} />
                  {p.max_tenure_days ? <Chip text={`Up to ${maxTenureMonths(p.max_tenure_days)} months`} /> : null}
                </View>
                {rules.length > 0 || p.required_document_types.length > 0 ? (
                  <View style={styles.rules} accessibilityLabel={`Who can apply: ${rules.join('. ')}`}>
                    <Text variant="caption" muted>
                      WHO CAN APPLY
                    </Text>
                    {rules.slice(0, 4).map((line) => (
                      <View key={line} style={styles.rule}>
                        <Ionicons name="checkmark-circle" size={15} color={colors.cyanDeep} />
                        <Text variant="small" style={{ flex: 1 }}>
                          {line}
                        </Text>
                      </View>
                    ))}
                    {p.required_document_types.length > 0 ? (
                      <View style={styles.rule}>
                        <Ionicons name="document-attach-outline" size={15} color={colors.cyanDeep} />
                        <Text variant="small" style={{ flex: 1 }}>
                          {p.required_document_types.length} document{p.required_document_types.length === 1 ? '' : 's'} to upload
                        </Text>
                      </View>
                    ) : null}
                  </View>
                ) : null}
                {draft ? (
                  <Text variant="small" color={colors.cyanDeep} style={{ fontFamily: font.bold, marginTop: space.sm }}>
                    You have a draft. Tap to continue it.
                  </Text>
                ) : null}
              </Card>
            </Animated.View>
          );
        })
      )}
    </Screen>
  );
}

function Chip({ text }: { text: string }) {
  return (
    <View style={styles.chip}>
      <Text variant="small" style={{ fontSize: 12, fontFamily: font.semibold }}>
        {text}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: space.md },
  icon: {
    width: 48,
    height: 48,
    borderRadius: radius.md,
    backgroundColor: colors.mint,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: space.md },
  chip: { backgroundColor: colors.surface, borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 4 },
  rules: { marginTop: space.md, gap: 6 },
  rule: { flexDirection: 'row', alignItems: 'center', gap: 6 },
});
