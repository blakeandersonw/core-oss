import { motion } from "motion/react";

interface GetStartedStepProps {
  onNext: () => void;
}

export default function GetStartedStep({ onNext }: GetStartedStepProps) {
  return (
    <div className="flex flex-col items-center text-center mx-auto">
      {/* Logo with glow effect */}
      <motion.div
        initial={{ opacity: 0, scale: 0.8, filter: "blur(20px)" }}
        animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
        transition={{
          duration: 1.1,
          ease: [0.16, 1, 0.7, 1],
        }}
        className="relative mb-10"
      >
        {/* Glow behind logo */}
        <motion.div
          initial={{ opacity: 0, scale: 0.5 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{
            duration: 0.8,
            ease: [0.16, 1, 0.7, 1],
            delay: 0.1,
          }}
          className="absolute inset-0 blur-2xl bg-gradient-to-br from-gray-200 to-gray-300 rounded-full scale-150 opacity-60"
        />
        <img
          src="/StarterStackLogo.png"
          alt="StarterStack"
          className="relative w-20 h-20"
        />
      </motion.div>

      {/* Title */}
      <motion.h1
        initial={{ opacity: 0, y: 16, filter: "blur(8px)" }}
        animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
        transition={{
          duration: 0.9,
          ease: [0.16, 1, 0.7, 1],
          delay: 0.15,
        }}
        className="text-4xl font-semibold text-gray-900 tracking-tight mb-4"
      >
        Welcome to StarterStack
      </motion.h1>

      {/* Description */}
      <motion.p
        initial={{ opacity: 0, y: 16, filter: "blur(6px)" }}
        animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
        transition={{
          duration: 0.9,
          ease: [0.16, 1, 0.7, 1],
          delay: 0.25,
        }}
        className="text-gray-500 text-lg leading-relaxed mb-12"
      >
        Your all-in-one workspace for teams.
        <br />
        Let's get you set up in a few quick steps.
      </motion.p>

      {/* CTA Button */}
      <motion.button
        initial={{ opacity: 0, y: 16, filter: "blur(6px)" }}
        animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
        transition={{
          duration: 0.9,
          ease: [0.16, 1, 0.7, 1],
          delay: 0.35,
        }}
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
        onClick={onNext}
        className="px-12 py-3 bg-gray-900 text-white rounded-full text-base font-medium shadow-lg shadow-gray-900/20 hover:bg-gray-800 transition-colors"
      >
        Get Started
      </motion.button>

      {/* Terms */}
      <motion.p
        initial={{ opacity: 0, filter: "blur(4px)" }}
        animate={{ opacity: 1, filter: "blur(0px)" }}
        transition={{
          duration: 0.6,
          delay: 0.5,
          ease: [0.16, 1, 0.7, 1],
        }}
        className="text-xs text-gray-400 mt-10 leading-relaxed"
      >
        By continuing, you agree to our{" "}
        <a href="/terms" className="underline hover:text-gray-600 transition-colors">
          Terms of Service
        </a>{" "}
        and{" "}
        <a href="/privacy" className="underline hover:text-gray-600 transition-colors">
          Privacy Policy
        </a>
        .
      </motion.p>
    </div>
  );
}
