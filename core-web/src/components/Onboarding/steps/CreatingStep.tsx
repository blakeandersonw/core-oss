import { useEffect, useState } from "react";
import { motion } from "motion/react";

interface CreatingStepProps {
  status: string;
}

export default function CreatingStep({ status }: CreatingStepProps) {
  const [dots, setDots] = useState("");

  useEffect(() => {
    const interval = setInterval(() => {
      setDots((prev) => (prev.length >= 3 ? "" : prev + "."));
    }, 500);
    return () => clearInterval(interval);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.3 }}
      className="flex flex-col items-center text-center py-16"
    >
      {/* Animated logo */}
      <motion.div
        animate={{
          scale: [1, 1.06, 1],
        }}
        transition={{
          duration: 2,
          repeat: Infinity,
          ease: "easeInOut",
        }}
      >
        <img src="/CoreLogo.png" alt="StarterStack" className="w-14 h-14 mb-8" />
      </motion.div>

      <h2 className="text-xl font-semibold text-gray-900 mb-3">
        {status}{dots}
      </h2>

      {/* Progress bar */}
      <div className="w-56 h-1 bg-gray-50 rounded-full mt-2 overflow-hidden">
        <motion.div
          className="h-full bg-gray-900 rounded-full"
          initial={{ width: "0%" }}
          animate={{ width: "100%" }}
          transition={{ duration: 4, ease: "easeInOut" }}
        />
      </div>
    </motion.div>
  );
}
