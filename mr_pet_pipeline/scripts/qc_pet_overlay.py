#!/usr/bin/env python3
"""Generate QC overlay images for PET on T1w anatomical images."""

import argparse
from pathlib import Path

import nibabel as nib
import numpy as np
import matplotlib.pyplot as plt


def overlay_slices(t1_data, pet_data, cmap='hot', alpha=0.5, vmin=None, vmax=None):
    """Extract mid-slice overlays for sagittal, coronal, and axial planes."""
    if vmin is None:
        vmin = np.percentile(pet_data, 2)
    if vmax is None:
        vmax = np.percentile(pet_data, 98)
    x_center = t1_data.shape[0] // 2
    y_center = t1_data.shape[1] // 2
    z_center = t1_data.shape[2] // 2
    overlays = {
        'sagittal': (t1_data[x_center, :, :].T, pet_data[x_center, :, :].T),
        'coronal': (t1_data[:, y_center, :].T, pet_data[:, y_center, :].T),
        'axial': (t1_data[:, :, z_center].T, pet_data[:, :, z_center].T),
    }
    return overlays, vmin, vmax


def plot_and_save(overlays, vmin, vmax, out_dir, tracer, session_id, cmap='hot', alpha=0.5):
    """Plot and save PNG images for each plane overlay."""
    for plane, (t1_slice, pet_slice) in overlays.items():
        plt.figure(figsize=(8, 8))
        plt.imshow(t1_slice, cmap='gray', interpolation='nearest')
        plt.imshow(pet_slice, cmap=cmap, alpha=alpha, vmin=vmin, vmax=vmax, interpolation='nearest')
        plt.axis('off')
        fname = f"{session_id}_{tracer}_{plane}_overlay.png"
        plt.savefig(Path(out_dir) / fname, bbox_inches='tight', pad_inches=0)
        plt.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pet-nifti', required=True, help='Coregistered PET image in T1w space (NIfTI)')
    parser.add_argument('--t1-mgz', required=True, help='T1 weighted image (FreeSurfer MGZ)')
    parser.add_argument('--out-dir', required=True, help='Directory to save QC PNG images')
    parser.add_argument('--tracer', required=True, help='Tracer name (e.g., tau, pib)')
    parser.add_argument('--session-id', required=True, help='Session identifier')
    parser.add_argument('--cmap', default='hot', help='Colormap for PET overlay')
    parser.add_argument('--alpha', type=float, default=0.5, help='Alpha blending for overlay')
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pet_img = nib.load(args.pet_nifti)
    pet_data = pet_img.get_fdata()
    t1_img = nib.load(args.t1_mgz)
    t1_data = t1_img.get_fdata()

    overlays, vmin, vmax = overlay_slices(t1_data, pet_data, cmap=args.cmap, alpha=args.alpha)
    plot_and_save(overlays, vmin, vmax, out_dir, args.tracer, args.session_id, cmap=args.cmap, alpha=args.alpha)


if __name__ == '__main__':
    main()
