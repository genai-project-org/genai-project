import { useMemo } from 'react';
import { Textarea } from '@/components/ui/textarea';
import { evaluateArithmetic } from '@/lib/safeArithmetic';
import { Calculator } from 'lucide-react';

// A labeled plain-text scratchpad for back-of-envelope math — deliberately
// NOT a real calculator UI. The one bit of polish: if the last non-empty
// line is a pure arithmetic expression (e.g. `500e6 * 0.1 * 5 / 86400`), its
// computed value is shown live underneath, using a safe hand-rolled parser
// (see lib/safeArithmetic.js) — never `eval()` on what the user typed.
export default function CalculationScratchpad({ value, onChange }) {
  const lastLineResult = useMemo(() => {
    const lines = (value || '').split('\n');
    const lastNonEmpty = [...lines].reverse().find((l) => l.trim());
    if (!lastNonEmpty) return null;
    return evaluateArithmetic(lastNonEmpty);
  }, [value]);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-sm font-medium">
        <Calculator className="h-3.5 w-3.5" /> Back-of-envelope calculations
      </div>
      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={'Work out your scale estimates here, e.g.:\n500e6 * 0.1 * 5 / 86400'}
        className="min-h-[120px] font-mono text-sm"
        data-testid="practice-calculation-textarea"
      />
      {lastLineResult !== null && (
        <div className="text-xs text-muted-foreground" data-testid="practice-calculation-live-result">
          = {lastLineResult.toLocaleString(undefined, { maximumFractionDigits: 6 })}
        </div>
      )}
    </div>
  );
}
