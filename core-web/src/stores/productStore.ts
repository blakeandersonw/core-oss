import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ProductType } from '../api/client';

interface ProductState {
  activeProductType: ProductType;
  setActiveProductType: (type: ProductType) => void;
}

export const useProductStore = create<ProductState>()(
  persist(
    (set) => ({
      activeProductType: 'workspace',
      setActiveProductType: (type) => set({ activeProductType: type }),
    }),
    {
      name: 'starterstack-product-storage-v1',
      partialize: (state) => ({
        activeProductType: state.activeProductType,
      }),
    }
  )
);
