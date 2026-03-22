/**
 * StakingPage — $FNDRY staking interface.
 * Allows users to stake tokens, earn rewards, and boost reputation tier.
 */
export default function StakingPage() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 p-8">
      <h1 className="text-2xl font-bold bg-gradient-to-r from-[#9945FF] to-[#14F195] bg-clip-text text-transparent">
        $FNDRY Staking
      </h1>
      <p className="text-gray-400 text-sm text-center max-w-md">
        Stake $FNDRY to earn rewards and boost your contributor reputation tier.
        Full staking dashboard coming soon.
      </p>
    </div>
  );
}
