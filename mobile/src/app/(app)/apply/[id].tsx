import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { BackHandler, Pressable, View } from 'react-native';
import Animated, { FadeIn } from 'react-native-reanimated';

import { loans } from '@/api/endpoints';
import { ApiError, messageFor } from '@/api/errors';
import type { Application, LoanProduct } from '@/api/types';
import { Button } from '@/components/Button';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, ErrorState, ProgressBar } from '@/components/States';
import { Text } from '@/components/Text';
import { BankPage, bankComplete } from '@/features/apply/BankPage';
import { pagesFor, type PageId, type WizardPage } from '@/features/apply/config';
import { DocumentChecklist, documentsComplete } from '@/features/apply/DocumentChecklist';
import { draftFrom, payloadFor, validateGuarantors, validatePage, type Draft } from '@/features/apply/draft';
import { FieldsPage } from '@/features/apply/FieldsPage';
import { GuarantorPage } from '@/features/apply/GuarantorPage';
import { ReviewPage } from '@/features/apply/ReviewPage';
import { keys, useApplication, useProducts } from '@/lib/queries';
import { colors, font, HIT, space } from '@/theme/tokens';

export default function ApplyWizardRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const app = useApplication(id);
  const products = useProducts();
  const product = products.data?.find((p) => p.code === app.data?.product_code);

  useEffect(() => {
    if (app.data && app.data.status !== 'draft') router.replace(`/applications/${id}`);
  }, [app.data, id]);

  if (app.isPending || products.isPending) {
    return (
      <Screen edges={['bottom']}>
        <CardSkeleton lines={4} />
      </Screen>
    );
  }
  if (app.isError || products.isError || !app.data || !product) {
    return (
      <Screen edges={['bottom']}>
        <ErrorState
          error={app.error ?? products.error}
          onRetry={() => {
            app.refetch();
            products.refetch();
          }}
        />
      </Screen>
    );
  }
  if (app.data.status !== 'draft') return null;
  return <Wizard application={app.data} product={product} />;
}

function pageValid(page: WizardPage, draft: Draft, application: Application): boolean {
  if (page.fields) return Object.keys(validatePage(page.fields, draft)).length === 0;
  if (page.id === 'bank') return bankComplete(draft);
  if (page.id === 'guarantor') return !validateGuarantors(draft.guarantors);
  if (page.id === 'documents') return documentsComplete(application);
  return false;
}

function Wizard({ application, product }: { application: Application; product: LoanProduct }) {
  const queryClient = useQueryClient();
  const pages = useMemo(() => pagesFor(product.workflow_steps), [product.workflow_steps]);
  const [draft, setDraft] = useState<Draft>(() => draftFrom(application));
  const [index, setIndex] = useState(() => {
    // A new draft starts at the top so pre-filled BVN details get checked.
    if (application.step <= 1) return 0;
    // A returning draft resumes at the first unfinished screen from where they left off.
    const from = Math.max(0, pages.findIndex((p) => p.stepIndex >= application.step));
    const initial = draftFrom(application);
    const firstIncomplete = pages.findIndex((p, i) => i >= from && !pageValid(p, initial, application));
    return firstIncomplete >= 0 ? firstIncomplete : from;
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [pageError, setPageError] = useState<string | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [submitErrors, setSubmitErrors] = useState<string[]>([]);

  const live = useApplication(application.id);
  const latest = live.data ?? application;
  const page = pages[index];
  const fields = page.fields ?? [];
  const isLast = index === pages.length - 1;

  const save = useMutation({
    mutationFn: (step: number) => loans.updateStep(application.id, { ...payloadFor(page, fields, draft, product.workflow_steps.length), step }),
    onSuccess: (updated) => queryClient.setQueryData(keys.application(application.id), updated),
  });

  const submit = useMutation({
    mutationFn: () => loans.submit(application.id),
    onSuccess: (updated) => {
      queryClient.setQueryData(keys.application(application.id), updated);
      queryClient.invalidateQueries({ queryKey: keys.applications });
      router.replace(`/applications/${application.id}`);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === 'APPLICATION_INCOMPLETE') setSubmitErrors(err.errors);
    },
  });

  const goTo = (i: number) => {
    setErrors({});
    setPageError(null);
    save.reset();
    setIndex(i);
  };

  const saveAndExit = useCallback(async () => {
    if (page.id !== 'documents' && page.id !== 'review') {
      try {
        await save.mutateAsync(page.stepIndex);
      } catch {
        return; // banner shows why; stay so nothing is lost
      }
    }
    queryClient.invalidateQueries({ queryKey: keys.applications });
    router.back();
  }, [page, save, queryClient]);

  const back = useCallback(() => {
    if (index > 0) goTo(index - 1);
    else saveAndExit();
    return true;
  }, [index, saveAndExit]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', back);
    return () => sub.remove();
  }, [back]);

  async function next() {
    if (page.fields) {
      const found = validatePage(page.fields, draft);
      setErrors(found);
      if (Object.keys(found).length) {
        setPageError('Please fix the highlighted fields.');
        return;
      }
    }
    if (page.id === 'bank' && !bankComplete(draft)) {
      setPageError('Choose your bank, enter your account number and wait for the account name.');
      return;
    }
    if (page.id === 'guarantor') {
      const problem = validateGuarantors(draft.guarantors);
      if (problem) {
        setPageError(problem);
        return;
      }
    }
    if (page.id === 'documents') {
      if (!documentsComplete(latest)) {
        setPageError('Upload every document on the list. You can save and finish later.');
        return;
      }
    }
    if (page.id !== 'documents') {
      try {
        await save.mutateAsync(pages[index + 1]?.stepIndex ?? page.stepIndex);
      } catch {
        return;
      }
    }
    goTo(index + 1);
  }

  const edit = (id: PageId) => {
    const i = pages.findIndex((p) => p.id === id);
    if (i >= 0) goTo(i);
  };


  return (
    <>
      <Stack.Screen
        options={{
          title: product.name,
          headerLeft: () => (
            <Pressable accessibilityRole="button" accessibilityLabel="Back" onPress={back} style={{ minWidth: HIT, minHeight: HIT, justifyContent: 'center' }}>
              <Ionicons name="chevron-back" size={26} color={colors.navy} />
            </Pressable>
          ),
          headerRight: () =>
            isLast ? null : (
              <Pressable accessibilityRole="button" onPress={saveAndExit} style={{ minHeight: HIT, justifyContent: 'center', paddingHorizontal: space.xs }}>
                <Text variant="small" color={colors.cyanDeep} style={{ fontFamily: font.bold }}>
                  Save & exit
                </Text>
              </Pressable>
            ),
        }}
      />
      <Screen
        key={page.id}
        edges={['bottom']}
        footer={
          isLast ? (
            <Button
              title="Submit application"
              icon="paper-plane"
              disabled={!agreed}
              loading={submit.isPending}
              onPress={() => {
                setSubmitErrors([]);
                submit.mutate();
              }}
            />
          ) : (
            <Button title="Continue" loading={save.isPending} onPress={next} />
          )
        }>
        <View style={{ gap: 6 }}>
          <Text variant="caption" muted>
            STEP {index + 1} OF {pages.length}
          </Text>
          <ProgressBar value={(index + 1) / pages.length} />
        </View>
        <Animated.View entering={FadeIn.duration(220)} style={{ gap: space.md }}>
          <View style={{ gap: 4 }}>
            <Text variant="title">{page.title}</Text>
            <Text muted>{page.subtitle}</Text>
          </View>

          {save.error ? <Banner message={`Couldn't save: ${messageFor(save.error)}`} /> : null}
          {submit.error && !(submit.error instanceof ApiError && submit.error.code === 'APPLICATION_INCOMPLETE') ? (
            <Banner message={messageFor(submit.error)} />
          ) : null}
          {pageError && page.id !== 'bank' && page.id !== 'guarantor' ? <Banner message={pageError} /> : null}

          {page.fields ? (
            <FieldsPage
              fields={page.fields.map((f) =>
                f.key === 'tenure_months' && product.max_tenure_days ? { ...f, max: Math.max(1, Math.floor(product.max_tenure_days / 30)) } : f,
              )}
              draft={draft}
              onChange={setDraft}
              errors={errors}
              onEdited={(key) => {
                const rest = { ...errors };
                delete rest[key];
                setErrors(rest);
                if (!Object.keys(rest).length) setPageError(null);
              }}
            />
          ) : page.id === 'bank' ? (
            <BankPage draft={draft} onChange={setDraft} error={pageError} />
          ) : page.id === 'guarantor' ? (
            <GuarantorPage draft={draft} onChange={setDraft} error={pageError} />
          ) : page.id === 'documents' ? (
            <DocumentChecklist application={latest} editable="all" />
          ) : (
            <ReviewPage
              application={latest}
              product={product}
              draft={draft}
              pages={pages.map((p) => p.id)}
              agreed={agreed}
              onAgree={setAgreed}
              onEdit={edit}
              submitErrors={submitErrors}
            />
          )}
        </Animated.View>
      </Screen>
    </>
  );
}
